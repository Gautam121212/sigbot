"""Professional return benchmarks — the yardstick for grading models."""
from sigbot.pro_benchmarks import daily_monthly_yearly, grade


def test_exceptional_core_return():
    g = grade(0.30, "core")
    assert "EXCEPTIONAL" in g.verdict


def test_worthless_core_return():
    g = grade(0.02, "core")               # 2% — below the 8% floor
    assert "worthless" in g.verdict


def test_losing_return_flagged():
    g = grade(-0.05, "core")
    assert "LOSING" in g.verdict


def test_venture_tier_uses_vc_thresholds():
    # 20% IRR is GOOD for a VC portfolio, not worthless
    assert "GOOD" in grade(0.20, "very-risky").verdict
    # but 5% is below even the VC floor
    assert "worthless" in grade(0.05, "very-risky").verdict


def test_risky_tier_needs_more_than_core():
    # 12% is good for core but worthless for a risky strategy (must clear 15%)
    assert "GOOD" not in grade(0.12, "risky").verdict


def test_daily_monthly_yearly_breakdown():
    d, m, y = daily_monthly_yearly(0.20)   # 20% a year on $100k
    assert abs(y - 20000) < 1
    assert 0 < d < m < y                   # daily < monthly < yearly
