"""Deployment readiness — real benchmarks, honest go/no-go."""
from __future__ import annotations

from sigbot.deployment_readiness import evaluate, readiness_report


def test_the_backtest_benchmarks_are_evaluated():
    crit = evaluate()
    names = {c.name for c in crit}
    assert any("70%" in n for n in names)
    assert any("Net-positive" in n for n in names)
    assert any("drawdown" in n or "-1.5" in n for n in names)


def test_a_failing_strategy_is_not_ready():
    bad = {2020: -2.0, 2021: -1.0, 2022: -3.0}
    crit = evaluate(bad)
    assert not all(c.passed for c in crit)


def test_zero_paper_history_is_not_yet_even_if_backtest_passes():
    """The 6-month path: a passing backtest still needs live proof."""
    report = readiness_report(paper_months=0)
    assert "NOT YET" in report
    assert "month" in report


def test_full_history_and_passing_backtest_is_ready():
    report = readiness_report(paper_months=6)
    assert "READY" in report
