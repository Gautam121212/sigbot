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


def test_big_beat_oversold_is_the_strongest_setup():
    from sigbot.news_oversold_beat import is_big_beat_oversold
    assert is_big_beat_oversold(surprise_pct=25, pre_rsi=30)   # big beat + oversold
    assert not is_big_beat_oversold(surprise_pct=8, pre_rsi=30)  # only a normal beat


def test_news_miss_short_is_a_short_signal():
    from sigbot.news_oversold_beat import news_miss_short
    # big miss on an overbought stock -> short
    assert news_miss_short(surprise_pct=-15, pre_rsi=70)
    # a small miss, or an oversold stock -> not a short
    assert not news_miss_short(surprise_pct=-3, pre_rsi=70)
    assert not news_miss_short(surprise_pct=-15, pre_rsi=40)
