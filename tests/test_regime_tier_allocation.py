"""Regime-switched tier allocation — the distribution fix."""
from sigbot.regime_tier_allocation import allocate, describe


def test_risk_on_overweights_growth():
    a = allocate(growth_cohort_trailing_return=0.20)
    assert a.regime == "risk-on"
    assert a.weights["very-risky"] > a.weights["stable"]   # overweight growth


def test_risk_off_rotates_to_stable():
    a = allocate(growth_cohort_trailing_return=-0.10)
    assert a.regime == "risk-off"
    assert a.weights["stable"] > a.weights["very-risky"]    # defend


def test_risk_on_expects_more_than_risk_off():
    on = allocate(0.20).expected_return
    off = allocate(-0.10).expected_return
    assert on > off


def test_risk_on_reaches_toward_twenty():
    """Leveraged risk-on allocation targets 20%+."""
    assert allocate(0.20).expected_return >= 0.20


def test_unknown_regime_is_balanced():
    a = allocate(None)
    assert a.regime == "unknown"


def test_describe_explains_the_distribution_fix():
    out = describe()
    assert "DISTRIBUTION" in out and "17.5%" in out
