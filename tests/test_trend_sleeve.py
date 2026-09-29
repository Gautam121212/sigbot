"""Trend sleeve — time-series momentum feasibility + correlation gate."""
from sigbot.trend_sleeve import TREND, describe, verdict


def test_parameter_plateau_is_real():
    """Long horizons (126-252d) positive, short (15-63d) not — structural."""
    assert TREND.plateau_is_real()


def test_trend_is_uncorrelated_with_inflection():
    """The gatekeeper PASS: near-zero full and downside correlation."""
    assert TREND.is_uncorrelated()
    assert abs(TREND.corr_full) < 0.2
    assert abs(TREND.corr_downside) < 0.2


def test_trend_does_not_improve_sharpe():
    """The honest FAIL: no allocation beats inflection-alone Sharpe."""
    assert not TREND.improves_sharpe()


def test_trend_is_a_small_defensive_overlay():
    """It earns a small weight as a drawdown-reducer, not a return engine."""
    w = TREND.best_defensive_weight()
    assert 0 < w <= 20


def test_describe_states_the_honest_verdict():
    out = describe()
    assert "NOT move the portfolio toward 30%" in out
    assert "DIVERSIFIER" in verdict()
