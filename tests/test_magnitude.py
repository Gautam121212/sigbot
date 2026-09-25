"""Magnitude signal — flags big-move potential for sized speculative bets."""
from sigbot.magnitude import is_high_magnitude, magnitude


def test_all_four_flags_gives_biggest_expected_move():
    r = magnitude(atr_pct=0.07, volume_ratio=4.0, rsi=15, mom20=0.30)
    assert r.score == 4
    assert r.expected_move > 0.15          # ~20%
    assert r.bet_size_pct == 1.0
    assert is_high_magnitude(r)


def test_no_flags_is_no_bet():
    r = magnitude(atr_pct=0.02, volume_ratio=1.0, rsi=50, mom20=0.05)
    assert r.score == 0 and r.bet_size_pct == 0.0
    assert not is_high_magnitude(r)


def test_bigger_move_gets_bigger_but_still_small_bet():
    two = magnitude(atr_pct=0.07, volume_ratio=4.0, rsi=50, mom20=0.05)
    four = magnitude(atr_pct=0.07, volume_ratio=4.0, rsi=15, mom20=0.30)
    assert four.bet_size_pct > two.bet_size_pct
    assert four.bet_size_pct <= 1.0        # still capped small — direction unknown
