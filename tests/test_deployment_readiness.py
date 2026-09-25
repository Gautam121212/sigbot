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


def test_risk_loop_verdict_catches_losing_bets(tmp_path):
    """The risk loop benchmark: if risky bets lose money, it must say so."""
    import json
    from sigbot.deployment_readiness import risk_loop_verdict
    f = tmp_path / "risk.jsonl"
    # 40 bets averaging negative
    f.write_text("\n".join(json.dumps({"outcome_multiple": -0.1}) for _ in range(40)))
    ok, note = risk_loop_verdict(str(f))
    assert not ok and "LOSE" in note


def test_risk_loop_verdict_passes_winning_bets(tmp_path):
    import json
    from sigbot.deployment_readiness import risk_loop_verdict
    f = tmp_path / "risk.jsonl"
    f.write_text("\n".join(json.dumps({"outcome_multiple": 0.2}) for _ in range(40)))
    ok, note = risk_loop_verdict(str(f))
    assert ok and "add value" in note


def test_risk_loop_too_few_bets_is_not_judged(tmp_path):
    import json
    from sigbot.deployment_readiness import risk_loop_verdict
    f = tmp_path / "risk.jsonl"
    f.write_text("\n".join(json.dumps({"outcome_multiple": 0.2}) for _ in range(5)))
    ok, note = risk_loop_verdict(str(f))
    assert not ok and "too few" in note
