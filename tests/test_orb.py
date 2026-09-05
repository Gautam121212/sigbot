"""Tests for the ORB backtester."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sigbot.orb import (
    ORBRules,
    backtest_orb,
    credit_spread_breakeven,
    evaluate,
    sensitivity,
    synthetic_intraday,
)


@pytest.fixture(scope="module")
def noise():
    return synthetic_intraday(days=250, seed=3)


NO_VIX = ORBRules(min_vix=None)


# ------------------------------------------------------------ null control

def test_no_edge_on_driftless_bars(noise):
    """A 1.5R target on a random walk should win near 40% and earn nothing."""
    res = evaluate(backtest_orb(noise, NO_VIX))
    assert res.n > 30
    assert 0.28 < res.win_rate < 0.50, f"win rate {res.win_rate:.1%} on noise"
    assert res.mean_r < 0.05, "positive expectancy on noise implies a bug"
    assert abs(res.t_stat) < 2.0


def test_the_tuning_loop_would_find_a_false_edge(noise):
    """The plan said: if win rate < 55%, adjust a parameter and retest.

    On data with no structure at all, some cells of the grid still show positive
    total R. Picking the best of twelve draws is not an estimate of anything —
    which is why `sensitivity` reports the surface instead of a winner.
    """
    surf = sensitivity(noise, NO_VIX)
    assert len(surf) == 12
    assert (surf["mean_r"] > 0).any(), "expected noise to produce some positive cells"
    assert (surf["mean_r"] > 0).mean() < 0.6, "too many positive cells on pure noise"
    assert surf["total_r"].max() > 0, "the tuning loop would have selected this cell"


# ----------------------------------------------------------------- mechanics

def _session(bars_spec, day="2024-01-02"):
    idx, rows = [], []
    t = pd.Timestamp(f"{day} 09:30")
    for o, h, l, c, v in bars_spec:
        rows.append(dict(open=o, high=h, low=l, close=c, volume=v))
        idx.append(t)
        t += pd.Timedelta(minutes=15)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def test_target_hit_gives_the_configured_r():
    bars = _session([
        (100.0, 101.0, 99.0, 100.0, 100),    # range: hi 101, lo 99, risk 2
        (100.0, 101.5, 100.0, 101.2, 500),   # breakout up on volume
        (101.2, 104.5, 101.0, 104.0, 300),   # target 101 + 1.5*2 = 104
    ])
    trades = backtest_orb(bars, ORBRules(min_vix=None, cost_per_side=0.0))
    assert len(trades) == 1
    assert trades[0].side == "BUY" and trades[0].exit_reason == "target"
    assert trades[0].r_multiple == pytest.approx(1.5)


def test_stop_hit_gives_minus_one_r():
    bars = _session([
        (100.0, 101.0, 99.0, 100.0, 100),
        (100.0, 101.5, 100.0, 101.2, 500),
        (101.2, 101.5, 98.5, 98.8, 300),
    ])
    t = backtest_orb(bars, ORBRules(min_vix=None, cost_per_side=0.0))[0]
    assert t.exit_reason == "stop" and t.r_multiple == pytest.approx(-1.0)


def test_ambiguous_bar_counts_as_a_loss():
    """Stop and target inside one bar: order is unknowable, so assume the worse."""
    bars = _session([
        (100.0, 101.0, 99.0, 100.0, 100),
        (100.0, 101.5, 100.0, 101.2, 500),
        (101.2, 105.0, 98.0, 100.0, 300),
    ])
    t = backtest_orb(bars, ORBRules(min_vix=None, cost_per_side=0.0))[0]
    assert t.exit_reason == "ambiguous_bar_counted_as_stop"
    assert t.r_multiple < 0


def test_low_volume_breakout_is_skipped():
    bars = _session([
        (100.0, 101.0, 99.0, 100.0, 1000),
        (100.0, 102.0, 100.0, 101.8, 100),   # breaks out, but volume is low
        (101.8, 103.0, 101.0, 102.0, 100),
    ])
    assert backtest_orb(bars, ORBRules(min_vix=None)) == []


def test_tight_range_is_skipped():
    bars = _session([
        (100.0, 100.05, 99.98, 100.0, 100),  # range 0.07% < 0.2% floor
        (100.0, 100.5, 100.0, 100.4, 500),
        (100.4, 100.9, 100.2, 100.8, 300),
    ])
    assert backtest_orb(bars, ORBRules(min_vix=None)) == []


def test_at_most_one_trade_per_session():
    bars = _session([
        (100.0, 101.0, 99.0, 100.0, 100),
        (100.0, 101.5, 100.0, 101.2, 500),
        (101.2, 101.3, 98.5, 98.6, 500),
        (98.6, 99.0, 97.0, 97.5, 500),
    ])
    assert len(backtest_orb(bars, ORBRules(min_vix=None))) == 1


def test_costs_reduce_r():
    bars = _session([
        (100.0, 101.0, 99.0, 100.0, 100),
        (100.0, 101.5, 100.0, 101.2, 500),
        (101.2, 104.5, 101.0, 104.0, 300),
    ])
    free = backtest_orb(bars, ORBRules(min_vix=None, cost_per_side=0.0))[0]
    paid = backtest_orb(bars, ORBRules(min_vix=None, cost_per_side=0.05))[0]
    assert paid.r_multiple < free.r_multiple


def test_vix_filter_blocks_quiet_days():
    bars = _session([
        (100.0, 101.0, 99.0, 100.0, 100),
        (100.0, 101.5, 100.0, 101.2, 500),
        (101.2, 104.5, 101.0, 104.0, 300),
    ])
    day = pd.DatetimeIndex(["2024-01-02"])
    assert backtest_orb(bars, ORBRules(), pd.Series([12.0], index=day)) == []
    assert len(backtest_orb(bars, ORBRules(), pd.Series([25.0], index=day))) == 1


# --------------------------------------------------------- credit spreads

def test_credit_spread_breakeven_math():
    assert credit_spread_breakeven(1.0, 0.15) == pytest.approx(0.85)
    assert credit_spread_breakeven(1.0, 0.20) == pytest.approx(0.80)
    assert credit_spread_breakeven(5.0, 1.00) == pytest.approx(0.80)


def test_a_quoted_83_percent_win_rate_can_be_a_loss():
    """Win rate is not edge when payoffs are asymmetric."""
    assert credit_spread_breakeven(1.0, 0.15) > 0.83
    with pytest.raises(ValueError):
        credit_spread_breakeven(1.0, 1.5)


def test_directional_breakeven_is_forty_percent():
    """Stop at the range edge with a 1.5R target: EV turns positive at 40%."""
    ev = lambda wr: wr * 1.5 - (1 - wr)  # noqa: E731
    assert ev(0.40) == pytest.approx(0.0)
    assert ev(0.55) == pytest.approx(0.375)
    assert ev(0.64) == pytest.approx(0.60)


def test_evaluate_handles_no_trades():
    res = evaluate([])
    assert res.n == 0 and "no trades" in res.summary()
    assert np.isnan(res.win_rate)
