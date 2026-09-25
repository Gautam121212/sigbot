"""Defensive regime signal — size down when crash risk is elevated."""
from sigbot.defensive import defensive_read, size_for


def test_bear_regime_sizes_down():
    r = defensive_read(ma50=90, ma200=100)   # 50 below 200 = bear
    assert r.bear_regime and r.size_multiplier < 1.0
    assert size_for(90, 100, 1.0) == 0.5


def test_bull_regime_is_normal_size():
    r = defensive_read(ma50=100, ma200=90)
    assert not r.bear_regime and r.size_multiplier == 1.0


def test_unknown_trend_is_normal_size():
    assert size_for(None, None, 1.0) == 1.0
