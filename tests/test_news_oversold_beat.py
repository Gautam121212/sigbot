"""Oversold-into-beat — the news mechanism edge."""
from sigbot.news_oversold_beat import expected_drift, is_oversold_beat


def test_oversold_beat_fires():
    assert is_oversold_beat(surprise_pct=10, pre_rsi=30)      # beat + oversold


def test_normal_beat_is_not_oversold_beat():
    assert not is_oversold_beat(surprise_pct=10, pre_rsi=55)  # beat but not oversold


def test_a_miss_is_not_a_beat():
    assert not is_oversold_beat(surprise_pct=2, pre_rsi=30)   # too small a surprise


def test_oversold_beat_expects_bigger_drift():
    oversold = expected_drift(10, 30)
    normal = expected_drift(10, 55)
    assert oversold > normal                                 # ~3.4% vs ~2.0%
    assert oversold > 3.0


def test_no_beat_no_drift():
    assert expected_drift(2, 30) == 0.0
