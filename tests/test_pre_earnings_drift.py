"""Pre-earnings drift — the leading news signal."""
from sigbot.pre_earnings_drift import expected_hit_rate, pre_earnings_lean


def test_upward_predrift_leans_buy():
    assert pre_earnings_lean(105.0, 100.0) == "BUY"      # +5% pre-drift


def test_downward_predrift_leans_sell():
    assert pre_earnings_lean(95.0, 100.0) == "SELL"      # -5%


def test_flat_predrift_is_no_lean():
    assert pre_earnings_lean(101.0, 100.0) is None       # +1%, too flat


def test_the_edge_is_real_but_modest():
    hit = expected_hit_rate()
    assert 0.53 < hit < 0.56                             # ~54.5%, above chance
