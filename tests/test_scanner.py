"""Tests for the candidate scanner.

Whether NSE answers today is not something a test settles — that is
`scripts/check_universe.py`, run from the machine that will do the fetching.
These check the parsing, the filters, and the refusals.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from sigbot.providers import scanner
from sigbot.providers.scanner import (
    MIN_DAILY_VOLUME, MIN_MARKET_CAP, _number, build, describe,
)

# NSE's index constituent format, not the full equity CSV. The full list is
# alphabetical and carries no volume, so taking its first N rows means taking
# companies beginning with A — which is how the screen came to propose
# AAATECH and AGRITECH over an entire board.
NSE_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Reliance Industries Ltd.,Oil Gas,RELIANCE,EQ,INE002A01018\n"
    "Tata Consultancy Services Ltd.,IT,TCS,EQ,INE467B01029\n"
)

NASDAQ_JSON = json.dumps({"data": {"rows": [
    {"symbol": "AAPL", "name": "Apple", "marketCap": "3000000000000",
     "volume": "50000000"},
    {"symbol": "TINY", "name": "Tiny Co", "marketCap": "1000000",
     "volume": "500"},
    {"symbol": "WARRANT.W", "name": "Warrant", "marketCap": "9000000000",
     "volume": "900000"},
]}})

COINGECKO_JSON = json.dumps([
    {"symbol": "btc", "name": "Bitcoin", "market_cap": 1.2e12,
     "total_volume": 3e10},
    {"symbol": "dust", "name": "Dust", "market_cap": 100.0,
     "total_volume": 10.0},
])


def _stub(monkeypatch, payloads):
    def fake(url, timeout=45.0):
        for fragment, body in payloads.items():
            if fragment in url:
                if isinstance(body, Exception):
                    raise body
                return body.encode()
        raise urllib.error.HTTPError(url, 404, "not stubbed", {}, None)

    monkeypatch.setattr(scanner, "_get", fake)


# ------------------------------------------------------------- parsing

def test_nse_reads_the_index_constituents(monkeypatch):
    """The index is the liquidity screen: NSE has already applied market cap
    and traded-value thresholds, which the raw equity CSV gave no way to do."""
    _stub(monkeypatch, {"nifty500list": NSE_CSV})
    found = scanner.nse_equities()
    assert [c.symbol for c in found] == ["RELIANCE.NS", "TCS.NS"]
    assert all(c.exchange == "NSE" for c in found)


def test_nse_falls_back_to_a_smaller_index(monkeypatch):
    """If the 500 list is unavailable the 200 and 100 still give a usable
    pool, rather than losing India entirely."""
    _stub(monkeypatch, {"nifty200list": NSE_CSV})
    assert len(scanner.nse_equities()) == 2


def test_stablecoins_are_never_candidates(monkeypatch):
    """PYUSD scored 18/100 — movability 0, reactivity 0, linkage 0. It is
    pegged to a dollar; it cannot move by construction."""
    payload = json.dumps([
        {"symbol": "usdt", "name": "Tether", "market_cap": 1e11,
         "total_volume": 9e10},
        {"symbol": "pyusd", "name": "PayPal USD", "market_cap": 1e9,
         "total_volume": 1e9},
        {"symbol": "sol", "name": "Solana", "market_cap": 8e10,
         "total_volume": 4e9},
    ])
    _stub(monkeypatch, {"coingecko": payload})
    assert [c.symbol for c in scanner.crypto()] == ["SOL-USD"]


def test_an_asset_that_cannot_move_is_rejected_by_the_screen():
    """Scoring such a thing 18/100 and letting it hold a slot wastes a
    hundredth of the board and a daily download forever."""
    import numpy as np
    import pandas as pd

    from sigbot.screener import score_asset

    idx = pd.bdate_range("2023-01-01", periods=600)
    flat = pd.Series(1.0 + np.random.default_rng(1).normal(0, 1e-6, len(idx)),
                     index=idx)
    bars = pd.DataFrame({"open": flat, "high": flat * 1.000001,
                         "low": flat * 0.999999, "close": flat,
                         "volume": 1e9}, index=idx)
    result = score_asset(bars, "PYUSD-USD", "crypto")
    assert not result.usable
    assert "no question it could answer" in (result.reject_reason or "")


def test_nasdaq_filters_on_cap_and_volume(monkeypatch):
    _stub(monkeypatch, {"nasdaq": NASDAQ_JSON})
    found = scanner.nasdaq_equities()
    assert [c.symbol for c in found] == ["AAPL"]
    assert found[0].market_cap >= MIN_MARKET_CAP
    assert found[0].volume >= MIN_DAILY_VOLUME


def test_non_alphabetic_tickers_are_dropped(monkeypatch):
    """Warrants, units and preferreds have their own price behaviour and no
    two-year history worth screening."""
    _stub(monkeypatch, {"nasdaq": NASDAQ_JSON})
    assert "WARRANT.W" not in [c.symbol for c in scanner.nasdaq_equities()]


def test_crypto_drops_dust(monkeypatch):
    _stub(monkeypatch, {"coingecko": COINGECKO_JSON})
    found = scanner.crypto()
    assert [c.symbol for c in found] == ["BTC-USD"]


@pytest.mark.parametrize("raw,expected", [
    ("$3,000,000", 3_000_000.0), ("1.2B", 1.2e9), ("50M", 5e7),
    ("900K", 900_000.0), ("NA", 0.0), ("", 0.0), (None, 0.0),
])
def test_numbers_survive_the_formats_these_sources_use(raw, expected):
    assert _number(raw) == expected


# ------------------------------------------------------------- failures

def test_one_dead_source_does_not_cost_the_others(monkeypatch):
    """Losing US names must not cost you the Indian ones."""
    _stub(monkeypatch, {"nifty500list": NSE_CSV,
                        "nasdaq": urllib.error.HTTPError(
                            "u", 403, "blocked", {}, None),
                        "coingecko": COINGECKO_JSON})
    universe = build()
    assert universe.by_exchange().get("NSE") == 2
    assert universe.by_exchange().get("CRYPTO") == 1
    assert "nasdaq" in universe.failures


def test_a_missing_source_is_named_not_hidden(monkeypatch):
    """A pool silently short of a whole exchange looks like a screen that
    preferred elsewhere."""
    _stub(monkeypatch, {"nifty500list": NSE_CSV})
    text = describe(build())
    assert "nasdaq FAILED" in text
    assert "never considered" in text


def test_an_empty_universe_is_returned_not_raised(monkeypatch):
    _stub(monkeypatch, {})
    universe = build()
    assert universe.candidates == []
    assert len(universe.failures) == 3


def test_describe_refuses_to_call_the_pool_a_ranking(monkeypatch):
    """Handing a wide pool to an uncorrected performance criterion would make
    the board worse while making it look better researched."""
    _stub(monkeypatch, {"nifty500list": NSE_CSV})
    text = describe(build())
    assert "not a ranking" in text
    assert "selects for luck" in text


def test_the_screen_accepts_a_generated_universe():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_screen.py"
           ).read_text()
    assert "--universe" in src
    assert "skew" in src, "the built-in list's bias should be stated"


def test_unknown_stablecoins_are_caught_by_name(monkeypatch):
    """USDG slipped past a hardcoded list of 18 tickers. Such a list goes stale
    the moment someone launches another one, and most of them are ones nobody
    has heard of yet."""
    payload = json.dumps([
        {"symbol": "usdg", "name": "Global Dollar", "market_cap": 1e9,
         "total_volume": 1e9},
        {"symbol": "fdusd", "name": "First Digital USD", "market_cap": 1e9,
         "total_volume": 1e9},
        {"symbol": "xyz", "name": "Some Stable Dollar", "market_cap": 1e9,
         "total_volume": 1e9},
        {"symbol": "sol", "name": "Solana", "market_cap": 8e10,
         "total_volume": 4e9},
    ])
    _stub(monkeypatch, {"coingecko": payload})
    assert [c.symbol for c in scanner.crypto()] == ["SOL-USD"]


def test_the_screen_refuses_a_churn_larger_than_the_weekly_cycle():
    """`cycle` may drop two assets a week and needs 100 checks first, because
    rotating the board destroys the accumulating record on everything removed.
    `--replace` had no such guard — the same decision the scheduled job is
    prevented from making, available in one command."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_screen.py"
           ).read_text()
    assert "MAX_SAFE_CHURN" in src
    assert "--force" in src
    assert "loses its accumulating record" in src


# ------------------------------------------- does the wider pool stick?

def test_the_weekly_cycle_reads_the_scanned_pool(tmp_path, monkeypatch):
    """Without this the cycle screens the hardcoded 156 forever, and the
    scanned pool is a one-off nobody remembers to re-run."""
    import json

    from sigbot.runner import _load_universe

    monkeypatch.chdir(tmp_path)
    (tmp_path / "universe.json").write_text(json.dumps(
        [{"symbol": "RELIANCE.NS", "kind": "equity"},
         {"symbol": "SOL-USD", "kind": "crypto"}]))

    loaded, note = _load_universe()
    assert loaded is not None
    assert [c.symbol for c in loaded] == ["RELIANCE.NS", "SOL-USD"]
    assert note == ""


def test_a_stale_pool_is_reported_not_used_silently(tmp_path, monkeypatch):
    """Companies list and delist. A pool built in January and used in June
    quietly stops containing anything new, and the screen then reports that
    nothing better exists — a statement about the file, not the market."""
    import json
    import os

    from sigbot.runner import _load_universe

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "universe.json"
    path.write_text(json.dumps([{"symbol": "X", "kind": "equity"}]))
    os.utime(path, (0, 0))

    loaded, note = _load_universe()
    assert loaded is not None, "a stale pool is still better than none"
    assert "days old" in note and "stale market" in note


def test_a_failed_refresh_keeps_the_existing_pool(tmp_path, monkeypatch):
    """Replacing a working pool with a half-fetched one is worse than using a
    slightly old one: the screen would report nothing better exists, meaning
    only that fewer things were offered."""
    import json
    import os

    from sigbot import runner
    from sigbot.providers import scanner as scanner_module

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "universe.json"
    path.write_text(json.dumps([{"symbol": "KEEP.NS", "kind": "equity"}]))
    os.utime(path, (0, 0))

    monkeypatch.setattr(scanner_module, "build",
                        lambda **_kw: scanner_module.Universe())
    assert runner._refresh_universe() is False
    assert json.loads(path.read_text())[0]["symbol"] == "KEEP.NS"


def test_a_fresh_pool_is_not_refetched(tmp_path, monkeypatch):
    import json

    from sigbot import runner

    monkeypatch.chdir(tmp_path)
    (tmp_path / "universe.json").write_text(json.dumps(
        [{"symbol": "X", "kind": "equity"}]))
    assert runner._refresh_universe() is False
