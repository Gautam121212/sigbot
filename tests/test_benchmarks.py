"""The monthly benchmark, and the checks built on it."""
from __future__ import annotations

from pathlib import Path

from sigbot.benchmarks import (
    ALL, BOTH_SCHOOLS, EXPECTED, HOLD_INDEX, MOMENTUM, MONTHLY_COST,
    OUT_OF_SAMPLE, WASHOUT,
    judge_month, judge_run,
)


def test_net_figures_subtract_costs_except_for_holding_the_index():
    assert abs(BOTH_SCHOOLS.net_avg - (0.0074 - MONTHLY_COST)) < 1e-9
    assert HOLD_INDEX.net_avg == HOLD_INDEX.avg_month, "holding costs nothing to run"


def test_the_benchmark_tells_the_uncomfortable_truth():
    """Measured fairly and after costs, the system TRAILED holding the index —
    in the period it was chosen on and, worse, in one it never saw. The first
    benchmark said it matched the index; that figure came from choosing
    stocks by today's size, and it was wrong."""
    for b in (BOTH_SCHOOLS, MOMENTUM, WASHOUT, OUT_OF_SAMPLE):
        assert b.net_avg < HOLD_INDEX.net_avg, b.name
    assert BOTH_SCHOOLS.net_avg < HOLD_INDEX.net_avg - 0.004
    assert abs(OUT_OF_SAMPLE.net_avg) < 0.002, "roughly nothing on unseen years"


def test_the_combination_has_the_shallowest_worst_month_but_the_index():
    """Its real advantage: similar returns, smaller falls."""
    assert BOTH_SCHOOLS.worst_month > HOLD_INDEX.worst_month


def test_sigbot_is_held_against_what_it_actually_runs():
    assert EXPECTED is BOTH_SCHOOLS


def test_one_losing_month_is_normal_not_a_flag():
    """About four months in ten lose money even for the best combination."""
    assert judge_month(-0.02)[0] == "NORMAL LOSS"
    assert judge_month(-0.08)[0] == "BELOW RANGE"


def test_a_short_run_is_too_early_and_a_lagging_one_is_named():
    assert judge_run([0.02] * 5)[0] == "TOO EARLY"
    assert judge_run([0.0] * 8)[0] == "BEHIND THE INDEX"
    assert judge_run([0.012] * 8)[0] == "ON TRACK"


def test_every_benchmark_is_internally_consistent():
    for b in ALL:
        assert b.worst_month <= b.bad_month_p10 <= b.median_month
        assert 0 < b.months_up < 1 and b.months >= 60


def test_the_playbook_and_the_code_quote_the_same_numbers():
    root = Path(__file__).resolve().parents[1]
    guide = (root / "PLAYBOOK.md").read_text()
    for figure in ("+0.54%", "+0.74%", "−16.61%", "2009–2015", "129 months"):
        assert figure in guide, f"{figure} missing — the playbook has drifted"


def test_live_months_are_judged_by_the_review(tmp_path):
    """Through the real ledger and paper book."""
    from sigbot.alignment import check_growth, monthly_returns
    from sigbot.shadow import ShadowLedger

    path = str(tmp_path / "s.db")
    ledger = ShadowLedger(path)
    pid = ledger.record("stocks", "X", "BUY", 0.7, 0.05, 100.0)
    ledger.resolve(pid, 110.0)

    months = monthly_returns(path)
    assert len(months) == 1 and months[0][1] > 0
    check = check_growth(months)
    assert check.verdict == "TOO EARLY", "one month is never a verdict"



def test_the_old_inflated_figures_are_gone():
    """+1.19% and +0.99% came from a filter that used today's company sizes.
    Nothing may quote them as the expectation again."""
    assert BOTH_SCHOOLS.avg_month != 0.0119
    assert round(BOTH_SCHOOLS.net_avg, 4) != 0.0099


def test_live_trading_is_limited_to_the_universe_that_was_tested():
    """The fair test covered only names trading over $20M a day."""
    from sigbot.scan import MIN_DOLLAR_VOLUME, liquid_enough

    assert MIN_DOLLAR_VOLUME == 20_000_000
    assert liquid_enough({"volume_ma_20": 1_000_000, "close": 50.0})
    assert not liquid_enough({"volume_ma_20": 1_000_000, "close": 4.0}), "$4M a day"
    assert not liquid_enough({"volume_ma_20": 1_000_000}), "no price, no trade"
