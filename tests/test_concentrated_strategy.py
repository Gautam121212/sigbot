"""Concentrated quality-growth — the best forward-validated config."""
from sigbot.concentrated_strategy import (
    DIVERSIFIED_RETURN, QUALITY_GROWTH_RETURN, is_quality_growth, verdict)


def test_a_quality_growth_name_qualifies():
    c = is_quality_growth(revenue_growth=0.35, gross_margin=0.72,
                          fcf_growth=0.4, above_200ma=True)
    assert c.in_strategy


def test_low_margin_disqualifies():
    c = is_quality_growth(0.35, 0.30, 0.4, True)
    assert not c.in_strategy


def test_downtrend_disqualifies():
    c = is_quality_growth(0.35, 0.72, 0.4, False)
    assert not c.in_strategy


def test_concentration_beats_diversification():
    """The core finding: concentrated ~16% beats diversified ~7%."""
    assert QUALITY_GROWTH_RETURN > DIVERSIFIED_RETURN * 2


def test_verdict_is_honest_about_20_percent():
    v = verdict()
    assert "NOT reachable" in v and "leverage" in v
    assert "16%" in v and "Do NOT stop" in v
