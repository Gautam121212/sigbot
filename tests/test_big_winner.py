"""Big-winner precursor — reverse-engineered from actual explosive moves."""
from sigbot.big_winner import BASE_50X, big_winner_setup


def test_the_precursor_fires_on_high_vol_rising_volume():
    r = big_winner_setup(atr_pct=0.12, momentum_20=0.15, volume_ratio=2.0)
    assert r.is_precursor
    assert r.tail_50x_prob > 0.05        # meaningfully above base
    assert r.lift > 10                   # many times the base rate


def test_oversold_weakness_is_NOT_a_precursor():
    """The key finding: big winners are NOT oversold. A weak, calm, falling
    stock is exactly what the precursor rejects."""
    r = big_winner_setup(atr_pct=0.02, momentum_20=-0.10, volume_ratio=0.8)
    assert not r.is_precursor


def test_each_leg_is_required():
    # high vol + volume but NOT rising -> no
    assert not big_winner_setup(0.12, -0.05, 2.0).is_precursor
    # rising + volume but calm -> no
    assert not big_winner_setup(0.03, 0.15, 2.0).is_precursor
    # high vol + rising but no volume -> no
    assert not big_winner_setup(0.12, 0.15, 1.0).is_precursor


def test_the_lift_over_base_is_large():
    r = big_winner_setup(0.12, 0.15, 2.0)
    assert r.tail_50x_prob / BASE_50X > 20      # ~27x measured
