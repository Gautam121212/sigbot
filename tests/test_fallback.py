"""Tests for the fallback chain and the green-triggered send.

The live sources are not called here. Whether Stooq is up today is not
something a test can settle; whether the chain falls through correctly is.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sigbot.providers.fallback import (
    CoinGeckoProvider, FallbackProvider, StooqProvider,
)


def _frame(n=60, broken=False):
    idx = pd.bdate_range("2026-06-01", periods=n)
    close = pd.Series(100 + np.arange(n) * 0.1, index=idx)
    df = pd.DataFrame({"open": close, "high": close * 1.01,
                       "low": close * 0.99, "close": close, "volume": 1e6})
    if broken:
        df.loc[df.index[5], "high"] = 1.0        # high below low
    return df


class _Fake:
    def __init__(self, name, mode):
        self.name, self.mode = name, mode

    def history(self, symbol, start, end, interval="1d"):
        if self.mode == "raise":
            raise RuntimeError("rate limited")
        if self.mode == "empty":
            return pd.DataFrame()
        return _frame(broken=self.mode == "broken")


def test_it_falls_through_to_the_next_source():
    fb = FallbackProvider([_Fake("a", "raise"), _Fake("b", "ok")])
    assert len(fb.history("X", "2026-06-01", "2026-08-01")) == 60
    assert fb.sources["X"] == "b"


def test_an_empty_frame_counts_as_a_failure():
    """A source that answers with nothing has not answered."""
    fb = FallbackProvider([_Fake("a", "empty"), _Fake("b", "ok")])
    fb.history("X", "2026-06-01", "2026-08-01")
    assert fb.sources["X"] == "b"


def test_impossible_bars_are_rejected_not_stored():
    """Accepting them would put the worst output into the store under the same
    name as the best."""
    fb = FallbackProvider([_Fake("a", "broken"), _Fake("b", "ok")])
    fb.history("Y", "2026-06-01", "2026-08-01")
    assert fb.sources["Y"] == "b"
    first = fb.attempts["Y"][0]
    assert not first.ok and "integrity" in first.reason


def test_total_failure_names_every_source():
    fb = FallbackProvider([_Fake("a", "raise"), _Fake("b", "empty")])
    with pytest.raises(RuntimeError) as exc:
        fb.history("X", "2026-06-01", "2026-08-01")
    assert "a:" in str(exc.value) and "b:" in str(exc.value)


def test_a_source_change_is_recorded_not_silent():
    """Bars from two sources use different adjustment conventions, so a return
    computed across the switch is partly an artifact of the change."""
    from sigbot import skips

    skips.reset()
    fb = FallbackProvider([_Fake("a", "ok"), _Fake("b", "ok")])
    fb.history("X", "2026-06-01", "2026-08-01")
    fb.providers[0] = _Fake("a", "raise")
    fb.history("X", "2026-06-01", "2026-08-01")

    assert fb.sources["X"] == "b"
    assert skips.report("source_changed", 0).skipped >= 1


def test_the_report_names_stitched_symbols():
    fb = FallbackProvider([_Fake("a", "raise"), _Fake("b", "ok")])
    fb.history("X", "2026-06-01", "2026-08-01")
    text = fb.report()
    assert "came from a fallback" in text
    assert "artifact of the change" in text


# ------------------------------------------------------- source limits

def test_stooq_refuses_intraday_rather_than_substituting_daily():
    with pytest.raises(ValueError, match="no 15m bars"):
        StooqProvider().history("AAPL", "2026-06-01", "2026-08-01", "15m")


def test_stooq_refuses_indian_tickers():
    with pytest.raises(ValueError, match="NSE/BSE"):
        StooqProvider().history("RELIANCE.NS", "2026-06-01", "2026-08-01")


def test_coingecko_refuses_equities():
    """A wrong answer that parses is worse than an error."""
    with pytest.raises(ValueError, match="crypto only"):
        CoinGeckoProvider().history("AAPL", "2026-06-01", "2026-08-01")


def test_us_tickers_get_the_suffix_stooq_needs():
    """Without this the fallback fails silently on every US symbol."""
    assert StooqProvider()._stooq_symbol("AAPL") == "aapl.us"
    assert StooqProvider()._stooq_symbol("BTC-USD") == "btcusd"


# ------------------------------------------------------- green triggers

def test_a_new_green_sends_even_when_the_page_is_unchanged(tmp_path, monkeypatch):
    """A model crossing its threshold is the event this system exists to
    catch. Suppressing it to save bandwidth would be the wrong trade."""
    import json

    from sigbot.runner import _green_count

    monkeypatch.chdir(tmp_path)
    (tmp_path / "app").mkdir()
    path = tmp_path / "app" / "data.json"

    path.write_text(json.dumps({"models": [{"tier": "silent"},
                                           {"tier": "watch"}]}))
    assert _green_count(str(path)) == 0

    path.write_text(json.dumps({"models": [{"tier": "trade"},
                                           {"tier": "silent"}]}))
    assert _green_count(str(path)) == 1

    path.write_text(json.dumps({"models": [{"tier": "trade"},
                                           {"tier": "alert"}]}))
    assert _green_count(str(path)) == 2


def test_a_missing_export_means_nothing_is_green(tmp_path, monkeypatch):
    from sigbot.runner import _green_count

    monkeypatch.chdir(tmp_path)
    assert _green_count("app/data.json") == 0


def test_the_page_refreshes_itself():
    """A tab left open on a desktop must not show yesterday's numbers."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "sigbot" / "report.py").read_text()
    assert 'http-equiv="refresh"' in src
    assert 'content="600"' in src, "should reload every ten minutes"


# ------------------------------------------- what your diagnostic revealed

def test_coingecko_snaps_the_window_to_a_legal_value(monkeypatch):
    """That endpoint accepts only 1, 7, 14, 30, 90, 180, 365. An earlier
    version computed the day count and sent it — 91 for a June-to-August
    range — which the API rejects. Every CoinGecko fetch failed while the API
    itself was fine."""
    import json
    import urllib.request

    seen = []

    class Resp:
        def read(self):
            return json.dumps([[1785614400000, 62958.0, 62959.0, 62263.0,
                                62476.0]] * 40).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        seen.append(req.full_url)
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    CoinGeckoProvider().history("BTC-USD", "2026-06-01", "2026-08-31")

    sent = int(seen[-1].split("days=")[1])
    assert sent in (1, 7, 14, 30, 90, 180, 365), f"days={sent} would be rejected"
    assert sent >= 91, "the window must cover the range asked for"


def test_stooq_rejects_the_html_block_page():
    """Stooq answers HTTP 200 with an HTML interstitial rather than CSV. At the
    HTTP level that looks like success, so only the header check catches it."""
    import urllib.request

    import pytest as _pytest

    class Resp:
        def read(self):
            return b'<!DOCTYPE html><html><head><meta charset="utf-8">'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    original = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=0: Resp()
    try:
        with _pytest.raises(RuntimeError, match="no data"):
            StooqProvider().history("AAPL", "2026-06-01", "2026-08-31")
    finally:
        urllib.request.urlopen = original


def test_twelvedata_is_optional_and_says_so(monkeypatch):
    """Without a key it must refuse, so the report shows Yahoo alone rather
    than implying a backup that cannot run."""
    from sigbot.providers.fallback import TwelveDataProvider

    monkeypatch.delenv("TWELVEDATA_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TWELVEDATA_KEY"):
        TwelveDataProvider().history("AAPL", "2026-06-01", "2026-08-31")


def test_twelvedata_leaves_crypto_to_coingecko():
    from sigbot.providers.fallback import TwelveDataProvider

    with pytest.raises(ValueError, match="CoinGecko"):
        TwelveDataProvider(key="x").history("BTC-USD", "2026-06-01", "2026-08-31")


def test_twelvedata_treats_an_error_body_as_a_failure(monkeypatch):
    """It reports errors inside a 200 response, so the status proves nothing."""
    import json
    import urllib.request

    from sigbot.providers.fallback import TwelveDataProvider

    class Resp:
        def read(self):
            return json.dumps({"status": "error",
                               "message": "run out of credits"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: Resp())
    with pytest.raises(RuntimeError, match="credits"):
        TwelveDataProvider(key="x").history("AAPL", "2026-06-01", "2026-08-31")
