"""Validation battery — sensitivity, Monte Carlo, matched controls."""
from sigbot.validation_battery import (
    MATCHED_CONTROL, MONTE_CARLO, SENSITIVITY, describe)


def test_parameter_sensitivity_is_robust():
    """Every neighboring config positive = plateau, not a cliff."""
    assert SENSITIVITY.is_robust()


def test_monte_carlo_reveals_historical_was_lucky():
    """The honest finding: realized 21.9% was top-quartile; median is ~14%."""
    assert MONTE_CARLO.historical_was_lucky()
    assert MONTE_CARLO.honest_forward_cagr() < MONTE_CARLO.historical_cagr


def test_monte_carlo_edge_rarely_loses_long_term():
    assert MONTE_CARLO.p_negative < 1.0            # <1% chance of long-term loss


def test_matched_control_confirms_real_alpha():
    """Signal beats the same-universe control on the median."""
    assert MATCHED_CONTROL.is_real_alpha()
    assert MATCHED_CONTROL.median_alpha() > 2.0


def test_describe_is_honest_about_forward_expectation():
    out = describe()
    assert "not this model alone" in out
    assert "14" in out                              # honest forward CAGR
