"""Tests for investment diligence and gap discovery.

The load-bearing test is `test_quoted_return_is_a_flag_not_evidence`: it encodes
the design decision that a promised return lowers a rating rather than raising
one.
"""
from __future__ import annotations

import pytest

from sigbot.investment import (
    CLASS_CHECKLIST,
    DILIGENCE,
    RED_FLAGS,
    AssetClass,
    InvestmentOpportunity,
    Severity,
    checklist,
    render_digest,
)
from sigbot.venture import (
    GAP_TYPES,
    OpportunityScore,
    RUBRIC,
    discovery_checklist,
    durability_warning,
    gap_brief,
)


def _dil(**overrides) -> dict[str, float]:
    base = {k: 8.0 for k in DILIGENCE}
    base.update(overrides)
    return base


# ---------------------------------------------------------- the core rule

def test_quoted_return_is_a_flag_not_evidence():
    """A promised return must lower the rating, never raise it."""
    quiet = InvestmentOpportunity("X", AssetClass.TOKEN, "th", _dil())
    loud = InvestmentOpportunity("X", AssetClass.TOKEN, "th", _dil(),
                                 claimed_return="10x in 6 months",
                                 claim_source="a newsletter")
    assert "claimed_return_stated" in loud.flags, "the flag must be added automatically"
    assert loud.rating < quiet.rating
    assert "RED FLAG, not as evidence" in loud.render()


def test_fatal_flag_caps_regardless_of_everything_else():
    perfect = _dil(**{k: 10.0 for k in DILIGENCE})
    op = InvestmentOpportunity("Y", AssetClass.TOKEN, "th", perfect,
                               flags=["guaranteed_return"])
    assert op.base_score == pytest.approx(100.0)
    assert op.rating <= 15.0
    assert op.verdict == "DO NOT PROCEED"


def test_each_fatal_flag_is_actually_fatal():
    perfect = {k: 10.0 for k in DILIGENCE}
    fatals = [f for f, (sev, *_) in RED_FLAGS.items() if sev is Severity.FATAL]
    assert len(fatals) >= 4
    for f in fatals:
        op = InvestmentOpportunity("Z", AssetClass.OTHER, "th", dict(perfect), flags=[f])
        assert op.rating <= 15.0, f"{f} did not cap the rating"
        assert op.verdict == "DO NOT PROCEED"


def test_severe_flags_cap_lower_than_perfect():
    perfect = {k: 10.0 for k in DILIGENCE}
    op = InvestmentOpportunity("W", AssetClass.FUND, "th", dict(perfect),
                               flags=["promoter_is_the_source"])
    assert op.rating <= 40.0
    assert "promotion until proven" in op.verdict


def test_moderate_flags_accumulate():
    mods = [f for f, (sev, *_) in RED_FLAGS.items() if sev is Severity.MODERATE]
    one = InvestmentOpportunity("a", AssetClass.IPO, "t", _dil(), flags=mods[:1])
    three = InvestmentOpportunity("a", AssetClass.IPO, "t", _dil(), flags=mods[:3])
    assert one.rating - three.rating == pytest.approx(16.0, abs=0.2)


def test_rating_never_goes_negative():
    mods = [f for f, (sev, *_) in RED_FLAGS.items() if sev is Severity.MODERATE]
    op = InvestmentOpportunity("a", AssetClass.TOKEN, "t",
                               {k: 0.0 for k in DILIGENCE}, flags=mods)
    assert op.rating == 0.0


# ------------------------------------------------------------- validation

def test_all_diligence_items_required():
    partial = {k: 8.0 for k in list(DILIGENCE)[:-1]}
    with pytest.raises(ValueError, match="silent 10"):
        InvestmentOpportunity("a", AssetClass.IPO, "t", partial)


def test_unknown_flag_rejected():
    with pytest.raises(ValueError, match="unknown red flags"):
        InvestmentOpportunity("a", AssetClass.IPO, "t", _dil(), flags=["vibes_are_off"])


def test_diligence_weights_sum_to_one_hundred():
    assert sum(w for w, _ in DILIGENCE.values()) == pytest.approx(100.0)


def test_score_out_of_range_rejected():
    with pytest.raises(ValueError, match="out of range"):
        InvestmentOpportunity("a", AssetClass.IPO, "t", _dil(exit_liquidity=-1.0))


# ----------------------------------------------------------------- output

def test_clean_opportunity_reaches_evaluable():
    op = InvestmentOpportunity(
        "Large listed IPO with audited filings", AssetClass.IPO, "thesis",
        _dil(disclosure_quality=9.0, source_independence=9.0, operating_history=9.0),
        sources=["SEBI filing", "audited FY26 statements"])
    assert op.rating >= 70
    assert "EVALUABLE" in op.verdict
    assert "not a forecast of return" in op.render()


def test_unblocking_questions_target_the_weakest_items():
    op = InvestmentOpportunity("a", AssetClass.PRIVATE, "t",
                               _dil(disclosure_quality=1.0, source_independence=2.0))
    qs = op.unblocking_questions()
    assert any("audited" in q for q in qs)
    assert len(qs) == 3


def test_no_sources_is_stated_plainly():
    op = InvestmentOpportunity("a", AssetClass.TOKEN, "t", _dil())
    assert "rating rests on nothing checkable" in op.render()


def test_every_asset_class_has_a_checklist():
    for ac in AssetClass:
        assert CLASS_CHECKLIST.get(ac)
        assert ac.value in checklist(ac)


def test_token_checklist_covers_supply_and_tax():
    text = checklist(AssetClass.TOKEN)
    assert "supply schedule" in text and "VDA" in text


def test_digest_details_strong_and_lists_the_rest():
    good = InvestmentOpportunity("Good", AssetClass.IPO, "t",
                                 _dil(disclosure_quality=10.0, source_independence=10.0,
                                      operating_history=9.0))
    bad = InvestmentOpportunity("Bad", AssetClass.TOKEN, "t", _dil(),
                                flags=["guaranteed_return"])
    text = render_digest([good, bad])
    assert "Not developed further" in text
    assert "DO NOT PROCEED" in text
    assert "not investment advice" in text
    assert text.count("diligence detail") == 1


def test_empty_digest_is_explicit():
    assert "No investment opportunities" in render_digest([])


# ------------------------------------------------------- gap discovery

def test_gap_types_have_signals_and_confirmations():
    assert len(GAP_TYPES) >= 7
    for name, (desc, signals, confirms) in GAP_TYPES.items():
        assert desc and len(signals) >= 3 and len(confirms) >= 2, name


def test_gap_brief_shows_how_to_confirm():
    text = gap_brief("supply_chain_shift")
    assert "what would confirm it is real" in text
    assert "landed cost" in text


def test_unknown_gap_type_rejected():
    with pytest.raises(ValueError, match="unknown gap type"):
        gap_brief("vibes")


def test_discovery_checklist_covers_everything():
    text = discovery_checklist()
    for name in GAP_TYPES:
        assert name.replace("_", " ").upper() in text


def test_low_durability_is_flagged_as_income_not_asset():
    """Dropshipping and import arbitrage: real income, not a compounding asset."""
    scores = {k: 8.0 for k in RUBRIC}
    scores["durability"] = 2.0
    op = OpportunityScore("Dropship niche", "thesis", "trigger", scores)
    warn = durability_warning(op)
    assert warn and "job that pays, not an asset" in warn
    scores["durability"] = 8.0
    assert durability_warning(OpportunityScore("t", "t", "t", scores)) is None
