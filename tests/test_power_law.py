"""Power-law portfolio model for ventures/ideas."""
from sigbot.power_law import MIN_BETS, is_worth_running, outlier_probability, plan


def test_twenty_bets_is_the_protection_threshold():
    assert not plan(5).protected and not plan(10).protected
    assert plan(20).protected
    assert abs(outlier_probability(20) - 0.64) < 0.02    # the famous 64%


def test_worth_running_only_above_the_threshold():
    assert is_worth_running(MIN_BETS)
    assert not is_worth_running(MIN_BETS - 1)


def test_follow_on_reserve_is_held_back():
    p = plan(20)
    # 20 bets share 60% of the sleeve (40% reserved) -> ~3% each
    assert 2.5 < p.per_bet_pct < 3.5


def test_more_bets_raise_outlier_odds():
    assert outlier_probability(30) > outlier_probability(20) > outlier_probability(10)
