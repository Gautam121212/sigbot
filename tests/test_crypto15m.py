"""Tests for Model E.

The model is Model B's machinery on a faster clock. What is genuinely
different is that costs dominate and observations are not independent — so
most of these are about the cost gate and about not letting a large check
count read as a large sample.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sigbot.crypto15m import (
    COST_MULTIPLE, HORIZON_BARS, MIN_BARS, MODEL_NAME, ROUND_TRIP_COST,
    forecast, summarise,
)


def _bars(vol=0.003, n=2000, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-07-01", periods=n, freq="15min", tz="UTC")
    r = rng.normal(0, vol, n)
    close = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
    return pd.DataFrame({
        "open": close.shift(1).bfill(),
        "high": close * (1 + abs(rng.normal(0, vol / 2, n))),
        "low": close * (1 - abs(rng.normal(0, vol / 2, n))),
        "close": close,
        "volume": rng.lognormal(10, 1, n)}, index=idx)


def test_a_move_that_cannot_cover_costs_is_recorded_but_not_tradeable():
    """A daily move of 1.5% clears a round trip with room; a fifteen-minute
    move of 0.05% does not clear it at all. A forecast that is right and
    unprofitable is worse than none — it fills the ledger with successes you
    could not have taken."""
    quiet = forecast("QUIET-USD", _bars(vol=0.0004))
    assert quiet is not None, "it must still be recorded"
    assert quiet.tradeable is False
    assert "right and unprofitable is worse than nothing" in quiet.reason


def test_a_large_move_clears_the_bar():
    lively = forecast("LIVELY-USD", _bars(vol=0.004))
    assert lively is not None and lively.tradeable is True


def test_the_cost_bar_is_far_above_a_round_trip():
    """At fifteen minutes the margin has to be wide, or the model learns the
    spread rather than the market."""
    assert COST_MULTIPLE >= 2.0
    assert ROUND_TRIP_COST * COST_MULTIPLE >= 0.002


def test_too_little_history_returns_nothing_rather_than_a_neutral_guess():
    """A fabricated 50% is indistinguishable from a measured one once it is in
    the ledger."""
    assert forecast("X-USD", _bars(n=100)) is None
    assert forecast("X-USD", None) is None


def test_the_model_records_under_its_own_name():
    """Pooling a one-hour horizon with a one-day horizon would mix two
    different questions into one hit rate."""
    assert MODEL_NAME == "crypto15m"
    assert HORIZON_BARS * 0.25 < 24, "this horizon is hours, not days"
    assert HORIZON_BARS * 0.25 >= 3, "and long enough that a person might act"


def test_the_summary_warns_that_checks_are_not_independent():
    """Ninety-six bars from one asset on one day are closer to one fact than
    ninety-six, and the count is the most available way to mislead yourself."""
    text = summarise([forecast("LIVELY-USD", _bars(vol=0.004))])
    assert "share most of their error" in text
    assert "market-day count" in text


def test_an_empty_run_is_called_a_fault():
    text = summarise([])
    assert "both are faults" in text
    assert "neither" in text and "quiet market" in text


def test_the_expected_move_comes_from_realised_magnitude_not_the_probability():
    """Those are different quantities, and conflating them inflates every
    expectation."""
    result = forecast("X-USD", _bars(vol=0.004))
    assert result is not None
    # A 52% probability must not imply a 52% move.
    assert abs(result.expected_move) < 0.10


@pytest.mark.parametrize("bad", ["1w", "3d", "tick"])
def test_unsupported_intervals_are_refused(bad):
    from sigbot.providers.binance import BinanceProvider

    with pytest.raises(ValueError, match="unsupported interval"):
        BinanceProvider().history("BTC-USD", "2026-07-01", "2026-08-01", bad)


def test_binance_refuses_equities():
    from sigbot.providers.binance import BinanceProvider

    with pytest.raises(ValueError, match="crypto only"):
        BinanceProvider().history("AAPL", "2026-07-01", "2026-08-01", "15m")


def test_usdt_pairs_map_to_usd_symbols():
    """Binance quotes against USDT. Treating the two as identical is a small
    lie that matters only in a crisis, when the peg is what breaks."""
    from sigbot.providers.binance import BinanceProvider

    assert BinanceProvider()._symbol("BTC-USD") == "BTCUSDT"


def test_the_model_runs_once_per_horizon():
    from datetime import timedelta

    from sigbot.coordinator import JOBS

    job = next(row for row in JOBS if row[0] == "crypto15m")
    # Once per horizon. Fifteen-minute runs produced ~9,600 forecasts a day of
    # almost entirely shared error — volume, not information.
    assert job[2] == timedelta(hours=3)
    assert job[3] is None, "crypto does not close"


def test_min_bars_leaves_room_to_hold_out():
    assert MIN_BARS >= 200


def test_the_fetch_window_is_one_request_per_pair():
    """45 days of 15-minute bars is 4,320 — five Binance requests each, and at
    a hundred pairs that is five hundred calls every quarter hour, redownloading
    the same history. A job that takes five times longer than it needs
    eventually overruns its window on a slow day and then alerts as a failure."""
    import re
    from pathlib import Path

    from sigbot.crypto15m import MIN_BARS
    from sigbot.providers.binance import MAX_BARS

    src = (Path(__file__).resolve().parents[1] / "sigbot" / "runner.py").read_text()
    window = re.search(r"timedelta\(days=(\d+)\)\)\.strftime\(\"%Y-%m-%d\"\)\n\n    out = \[\]",
                       src)
    days = int(window.group(1)) if window else 45

    bars = days * 96
    assert bars <= MAX_BARS, f"{days} days is {bars} bars, more than one request"
    assert bars >= MIN_BARS * 2, "must still leave room to fit and hold out"


def test_the_pair_count_is_a_choice_not_a_limit(monkeypatch):
    """Binance allows a thousand bars a request and does not charge, so the
    cost of widening is download time rather than quota."""
    import importlib

    monkeypatch.setenv("SIGBOT_CRYPTO_PAIRS", "40")
    import sigbot.runner as runner

    importlib.reload(runner)
    assert runner.CRYPTO15M_PAIRS == 40
    monkeypatch.delenv("SIGBOT_CRYPTO_PAIRS")
    importlib.reload(runner)


def test_a_wider_pair_list_does_not_multiply_the_evidence():
    """A hundred pairs on one day still observes one day, and on a day the
    whole market moves together they are closer to one observation than a
    hundred."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "sigbot" / "runner.py").read_text()
    assert "still observes one day" in src
    assert "closer to one observation" in src


def test_the_intraday_model_resolves_against_binance_not_yahoo():
    """Every model used to resolve against Yahoo daily closes. For crypto15m
    that is the wrong source and the wrong horizon at once: the forecast came
    from a Binance fifteen-minute bar and was scored against a Yahoo daily
    close of a symbol Yahoo may not carry.

    That is where "APT-USD, average move -100.0%" came from — a missing quote
    read as a price of zero — and a 64% move on a one-hour horizon. A wrong
    resolution is worse than none: every hit rate computed from it is fiction.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "sigbot" / "runner.py").read_text()
    assert "_intraday_price" in src
    assert "BinanceProvider" in src
    assert "wrong source and the wrong horizon" in src


def test_pegged_pairs_never_reach_the_intraday_ledger():
    """USD1 and RLUSD both reached it and produced fourteen and thirteen misses
    each on moves of 0.1% and 0.0%. A pegged asset cannot move, so every
    forecast on one is a coin flip on rounding error."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "sigbot" / "providers"
           / "binance.py").read_text()
    assert 'base.startswith("USD")' in src
    assert 'base.endswith("USD")' in src


def test_a_null_is_not_overclaimed_either():
    """'Never, however long it runs' is a claim about the true hit rate made
    from a measured one. Overclaiming a null is the same error as overclaiming
    an edge, pointed the other way."""
    from sigbot.export_app import _status_line
    from sigbot.tiers import Tier

    line = _status_line(Tier.SILENT, 300, 0.48, 0)
    assert "never clear the bar, however long it runs" not in line
    assert "whether it stays this low" in line
