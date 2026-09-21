"""Core and satellite: the account is the index plus what trades add beyond it."""
from __future__ import annotations

import inspect

import sigbot.runner as runner
from sigbot.benchmarks import (
    ACCOUNT_NET_MONTH, HOLD_INDEX, SATELLITE_IN, SATELLITE_OOS, SURVIVORSHIP_HAIRCUT,
)


def test_only_setups_that_add_return_beyond_the_index_get_capital():
    """Momentum's gains were the market's: -0.05% beyond the index since 2016,
    -0.83% on 2009-15. Under core and satellite it duplicates the core."""
    assert runner.SATELLITE_STYLES == {"reversion"}
    src = inspect.getsource(runner.run_stocks)
    assert "hit.candidate.style not in SATELLITE_STYLES" in src
    assert "recorded, not taken" in src


def test_the_ladder_uses_the_edge_after_the_survivorship_haircut():
    """Dip-buying is the strategy most flattered by bankrupt companies being
    missing. The haircut turns the unseen years from passing to not."""
    assert SURVIVORSHIP_HAIRCUT >= 0.002
    assert SATELLITE_OOS.monthly_alpha(0) > 0.002, "raw: would pass"
    assert SATELLITE_OOS.monthly_alpha() < 0.002, "after the haircut: does not"


def test_the_account_beats_the_index_but_only_modestly():
    assert ACCOUNT_NET_MONTH > HOLD_INDEX.avg_month
    assert ACCOUNT_NET_MONTH - HOLD_INDEX.avg_month < 0.005
    assert SATELLITE_IN.t_stat >= 2 and SATELLITE_OOS.t_stat >= 2


def test_the_ladder_reads_the_core_satellite_account():
    from sigbot.promotion import evaluate
    ev = runner.gather_promotion_evidence()
    assert abs(ev.hist_net_month - ACCOUNT_NET_MONTH) < 1e-12
    v = evaluate(ev)
    passed = {c.name for c in v.criteria if c.passed}
    assert "Fair history beats holding the index" in passed
    assert "Unseen years added return beyond the index" not in passed
    assert v.stage == "PAPER"


def test_news_and_crypto_benchmarks_say_what_the_data_said():
    from sigbot.benchmarks import CRYPTO_HOLD, CRYPTO_TREND_200, NEWS_EARNINGS
    big_beat = NEWS_EARNINGS["big beat"]
    assert big_beat[0] > 0.015 and abs(big_beat[2]) < 0.005, "priced on the day"
    assert NEWS_EARNINGS["in line"][0] < 0, "matching forecasts is punished"
    assert CRYPTO_TREND_200["max_drawdown"] > CRYPTO_HOLD["max_drawdown"]
    assert CRYPTO_TREND_200["growth_x"] < CRYPTO_HOLD["growth_x"]
