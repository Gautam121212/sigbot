"""Ideas structural signal — which catalysts precede real opportunities."""
from sigbot.ideas_signal import idea_strength, is_strong_opportunity


def test_material_agreement_midcap_is_strong():
    s = idea_strength("material_agreement", market_cap=1e9)
    assert s.strong and is_strong_opportunity(s)
    assert s.big_move_prob > 0.075


def test_large_cap_material_agreement_is_weak():
    """A mega-cap barely moves on one deal — the recombination finding."""
    s = idea_strength("material_agreement", market_cap=5e9)
    assert not s.strong


def test_exec_change_is_a_weak_catalyst():
    s = idea_strength("exec_change", market_cap=1e9)
    assert not s.strong and "weak" in s.note


def test_earnings_is_the_strongest_catalyst_type():
    from sigbot.ideas_signal import CATALYST_STRENGTH
    assert CATALYST_STRENGTH["earnings"] == max(CATALYST_STRENGTH.values())


def test_midcap_beats_largecap_for_material_agreements():
    mid = idea_strength("material_agreement", 1e9).big_move_prob
    large = idea_strength("material_agreement", 5e9).big_move_prob
    assert mid > large


def test_healthcare_deal_is_strongest_sector():
    from sigbot.ideas_signal import idea_strength_full
    hc = idea_strength_full("material_agreement", 1e9, "Health Care")
    fin = idea_strength_full("material_agreement", 1e9, "Financials")
    assert hc.big_move_prob > fin.big_move_prob
    assert hc.strong and not fin.strong


def test_stacked_catalyst_adds_strength():
    from sigbot.ideas_signal import idea_strength_full
    single = idea_strength_full("material_agreement", 1e9, "Information Technology")
    stacked = idea_strength_full("material_agreement", 1e9, "Information Technology",
                                 stacked=True)
    assert stacked.big_move_prob > single.big_move_prob


def test_large_cap_still_trimmed_in_strong_sector():
    from sigbot.ideas_signal import idea_strength_full
    mid = idea_strength_full("material_agreement", 1e9, "Health Care")
    large = idea_strength_full("material_agreement", 5e9, "Health Care")
    assert large.big_move_prob < mid.big_move_prob
