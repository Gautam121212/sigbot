"""Exceptional-profile screener — the 10-bagger DNA, honestly bounded."""
from sigbot.exceptional_profile import (
    BASKET_AVG_RETURN, exceptional_profile, honest_ceiling)


def test_the_ten_bagger_dna_is_recognized():
    r = exceptional_profile(revenue_growth_yoy=0.60, gross_margin=0.70,
                            operating_margin=-0.10)
    assert r.is_exceptional_profile
    assert r.tenbagger_odds > 3          # 3.8x baseline


def test_a_profitable_grower_is_not_the_profile():
    """The 10-bagger DNA is UNPROFITABLE (burning cash to grow)."""
    r = exceptional_profile(0.60, 0.70, 0.20)   # profitable
    assert not r.is_exceptional_profile


def test_a_low_margin_company_is_not_the_profile():
    r = exceptional_profile(0.60, 0.30, -0.10)  # low margin
    assert not r.is_exceptional_profile


def test_the_basket_ceiling_is_honestly_modest():
    """The profile is the right universe but averages only ~7% — not exceptional."""
    assert BASKET_AVG_RETURN < 0.10


def test_honest_ceiling_states_the_data_gap():
    c = honest_ceiling()
    assert "alt-data" in c and "arbitraged" in c
