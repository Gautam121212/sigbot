"""Tests for the news-to-business bridge and the claim evaluator wiring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sigbot.investment import (
    AssetClass, DILIGENCE, InvestmentOpportunity, parse_claimed_return, render_digest,
)
from sigbot.types import Article
from sigbot.venture import PLAN_THRESHOLD
from sigbot.venture_news import (
    CARRY_COMMODITIES, UNKNOWABLE_FROM_NEWS, VentureNewsScanner, enrich, render_candidates,
)

NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _a(title, summary="", source="Reuters", mins=0):
    t = NOW - timedelta(minutes=mins)
    return Article(title[:8], title, summary, "u", source, t, t)


# --------------------------------------------------- claim parsing (bug 1)

@pytest.mark.parametrize("claim,expected", [
    ("8x in 6 months", (8.0, 0.5)),
    ("10X", (10.0, 1.0)),
    ("300% over 2 years", (4.0, 2.0)),
    ("3x over 18 months", (3.0, 1.5)),
    ("2x in 4 weeks", (2.0, 4 / 52)),
])
def test_claim_parser_handles_real_wordings(claim, expected):
    got = parse_claimed_return(claim)
    assert got[0] == pytest.approx(expected[0])
    assert got[1] == pytest.approx(expected[1], rel=1e-6)


def test_claim_parser_refuses_to_invent():
    assert parse_claimed_return(None) is None
    assert parse_claimed_return("great opportunity") is None
    assert parse_claimed_return("0.5x") is None, "a loss is not a claimed return"


def test_render_does_not_crash_on_a_claim():
    """The proposed parser called re.IGNORECASE(claim), which raises TypeError."""
    op = InvestmentOpportunity("T", AssetClass.TOKEN, "th", {k: 5.0 for k in DILIGENCE},
                               claimed_return="8x in 6 months", claim_source="a channel")
    text = op.render()
    assert "CLAIM EVALUATED" in text and "to 1 against" in text


def test_every_asset_class_can_be_evaluated():
    """CRYPTO and OTHER were missing from the mapping, silently skipping evaluation."""
    for ac in AssetClass:
        op = InvestmentOpportunity("x", ac, "t", {k: 5.0 for k in DILIGENCE},
                                   claimed_return="5x in 1 year")
        assert op.claim_assessment is not None, f"{ac} produced no assessment"


def test_assumed_horizon_is_disclosed():
    op = InvestmentOpportunity("x", AssetClass.TOKEN, "t", {k: 5.0 for k in DILIGENCE},
                               claimed_return="10x")
    assert op.horizon_was_assumed
    assert "one year was assumed" in op.render()


def test_claim_survives_the_severe_cap(  ):
    """A claimed return caps the rating at 40, so it never reaches the detailed
    section — the evaluation must still appear somewhere."""
    op = InvestmentOpportunity("Promoted token", AssetClass.TOKEN, "t",
                               {k: 9.0 for k in DILIGENCE}, claimed_return="8x in 1 year")
    assert op.rating <= 40.0
    assert "to 1 against" in op.brief()
    digest = render_digest([op])
    assert "Claimed returns, checked against base rates" in digest
    assert "TAIL OUTCOME" in digest or "EXTRAORDINARY" in digest


# --------------------------------------------- news scanner ceiling (bug 2)

def test_news_alone_cannot_reach_the_plan_threshold():
    """The proposed heuristic topped out at 66.1 against a threshold of 80,
    so the full-plan branch could never fire. Now that limit is explicit."""
    arts = [_a("Compliance deadline forces mandatory certification for exporters",
               "Firms must comply by December or lose tender eligibility.")]
    cands = VentureNewsScanner().scan(arts)
    assert cands
    for c in cands:
        assert c.score < PLAN_THRESHOLD
        assert set(c.needs_enrichment) == set(UNKNOWABLE_FROM_NEWS)
        assert "cannot answer" in c.render() or "must" in c.render()


def test_ceiling_is_reported_and_reachable():
    arts = [_a("No distributor for medical devices in eastern states",
               "Hospitals report they cannot find a local supplier; no regional presence.")]
    c = VentureNewsScanner().scan(arts)[0]
    assert c.ceiling > c.score
    assert c.can_reach_plan, "a strong gap should be able to reach 80 after enrichment"
    assert "up to" in c.render()


def test_enrichment_unlocks_a_plan():
    arts = [_a("No distributor for medical devices in eastern states",
               "Hospitals cannot find a local supplier; no regional presence.")]
    c = VentureNewsScanner().scan(arts)[0]
    op = enrich(c, demand_evidence=9.0, distribution=9.0, skill_fit=8.0)
    assert op.total > c.score
    assert op.total <= c.ceiling


def test_enrichment_cannot_overwrite_news_evidence():
    arts = [_a("Tariff change forces alternate sourcing for importers", "customs circular")]
    c = VentureNewsScanner().scan(arts)[0]
    with pytest.raises(ValueError, match="may not be overridden"):
        enrich(c, evidence_quality=10.0)
    with pytest.raises(ValueError, match="out of range"):
        enrich(c, distribution=11.0)


# ----------------------------------------------- commodities (bug 4)

def test_multiword_commodities_are_matched():
    """A \\w+ capture reads 'shortage of palm oil' as 'palm' and drops it."""
    for c in ("palm oil", "natural gas", "iron ore", "copper"):
        cands = VentureNewsScanner().scan([_a(f"Analysts warn of a shortage of {c} next year")])
        assert cands and cands[0].commodity == c, f"{c} not detected"


def test_commodity_candidate_points_at_the_carry_test():
    c = VentureNewsScanner().scan([_a("Deficit in copper expected through 2027")])[0]
    assert c.commodity == "copper"
    assert "carry test" in c.render()
    assert c.opportunity.scores["capital_required"] <= 4.0
    assert c.opportunity.scores["durability"] <= 4.0


def test_carry_list_has_no_unmatchable_entries():
    for c in CARRY_COMMODITIES:
        assert VentureNewsScanner().scan([_a(f"shortage of {c} reported")])


# ------------------------------------------------------ one alert per story

def test_one_candidate_per_story():
    """The proposed scanner emitted a signal per matching keyword family, so a
    single article could produce five near-identical alerts."""
    arts = [_a("Tariff and compliance deadline create supply chain backlog",
               "Mandatory certification, no distributor, customs delays, overpriced.")]
    assert len(VentureNewsScanner().scan(arts)) == 1


def test_low_quality_sources_are_dropped():
    assert VentureNewsScanner().scan([_a("shortage of copper", source="randomblog.xyz")]) == []


def test_syndicated_coverage_raises_strength_not_count():
    base = _a("Mandatory certification deadline hits exporters", "must comply", "Reuters")
    dupe = _a("Mandatory certification deadline hits exporters now", "must comply", "CNBC", 5)
    one = VentureNewsScanner().scan([base])
    two = VentureNewsScanner().scan([base, dupe])
    assert len(two) == 1
    assert two[0].opportunity.scores["evidence_quality"] >= one[0].opportunity.scores["evidence_quality"]


def test_render_states_no_plan_from_news_alone():
    cands = VentureNewsScanner().scan([_a("shortage of nickel reported by miners")])
    assert "No candidate reaches a plan on news alone" in render_candidates(cands)
    assert "No business-opportunity candidates" in render_candidates([])
