"""Venture structural signal — the fundamentals of big winners."""
from sigbot.venture_signal import is_outlier_candidate, venture_signal


def test_hypergrowth_cash_burning_is_the_outlier_profile():
    s = venture_signal(revenue_growth_yoy=0.60, operating_margin=-0.15)
    assert s.is_candidate and is_outlier_candidate(s)
    assert s.double_probability > 0.09        # ~11%


def test_hypergrowth_profitable_is_a_weaker_profile():
    """The counterintuitive finding: profitable hypergrowth doubles LESS."""
    burning = venture_signal(0.60, -0.15)
    profitable = venture_signal(0.60, 0.20)
    assert burning.double_probability > profitable.double_probability
    assert not is_outlier_candidate(profitable)


def test_slow_growth_is_not_a_candidate():
    s = venture_signal(0.05, 0.10)
    assert not s.is_candidate


def test_fast_growth_is_a_moderate_candidate():
    s = venture_signal(0.25, 0.05)
    assert s.is_candidate and not is_outlier_candidate(s)


def test_growth_predicts_doubling_monotonically():
    hyper = venture_signal(0.60, -0.15).double_probability
    fast = venture_signal(0.25, 0.05).double_probability
    slow = venture_signal(0.05, 0.10).double_probability
    assert hyper > fast > slow


def test_hypergrowth_high_margin_is_the_top_profile():
    """The fuller pass: hypergrowth + high gross margin is the strongest (9.4%)."""
    s = venture_signal(revenue_growth_yoy=0.60, operating_margin=-0.10,
                       gross_margin=0.70)
    assert s.profile == "hypergrowth high-margin"
    assert s.double_probability > 0.09
