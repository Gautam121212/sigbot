"""The blowup model — asymmetric-explosive setups."""
from sigbot.blowup import blowup_setup, expected_value


def test_the_full_setup_fires():
    r = blowup_setup(atr_pct_60=0.02, atr_pct_250=0.04, close=110, sma_200=100,
                     volume=3e6, volume_ma_20=1.5e6)
    assert r.is_setup
    assert r.tail_up_prob > 0.1          # >10% chance of a 30%+ move
    assert 0 < r.size_pct <= 1.0         # tiny lottery-ticket size


def test_missing_any_leg_is_no_setup():
    # no compression
    assert not blowup_setup(0.05, 0.04, 110, 100, 3e6, 1.5e6).is_setup
    # below 200MA
    assert not blowup_setup(0.02, 0.04, 90, 100, 3e6, 1.5e6).is_setup
    # no volume surge
    assert not blowup_setup(0.02, 0.04, 110, 100, 1e6, 1.5e6).is_setup


def test_the_lottery_ticket_has_positive_ev():
    r = blowup_setup(0.02, 0.04, 110, 100, 3e6, 1.5e6)
    assert expected_value(r) > 0         # fat upside tail beats capped downside


def test_missing_data_is_safe():
    r = blowup_setup(None, 0.04, 110, 100, 3e6, 1.5e6)
    assert not r.is_setup
