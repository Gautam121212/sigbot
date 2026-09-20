"""Tests for the listing scorer.

The design question was whether to score all ten tests when the coverage speaks
to three. It does not: unobserved criteria leave the denominator rather than
being filled with a neutral value, because 60/100 reads as a judgement and
"34 of a possible 41" reads as what it is.
"""
from __future__ import annotations

import pytest

from sigbot.listings import (
    GREEN, GREY, TESTS, TOTAL_POSSIBLE, from_article, score_listing,
)

RICH = ("Acme IPO opens Monday. The company turned profitable with net profit "
        "of Rs 210 crore; revenue grew 34% CAGR. The fresh issue funds capex "
        "and debt repayment. Anchor investors include mutual funds. Analysts "
        "call it reasonably priced. Kotak and Axis Capital are lead managers. "
        "Oversubscribed on day one.")
THIN = "Beta Textiles IPO to open next week, price band announced."
POOR = ("Gamma IPO is a pure OFS with promoters selling; loss-making with cash "
        "burn, richly valued, facing a SEBI notice over related party deals. "
        "Weak response so far.")


def test_unobserved_tests_leave_the_denominator():
    """Neutralising them instead would turn silence into a middling verdict."""
    thin = score_listing("Beta", THIN)
    assert thin.possible < TOTAL_POSSIBLE * 0.35
    assert thin.scored <= thin.possible
    assert "out of a possible" in thin.render_text()
    assert "/100" not in thin.render_text()


def test_thin_coverage_and_bad_news_are_different_states():
    """Collapsing them would hide a good listing that had thin coverage on the
    day it was scanned."""
    thin = score_listing("Beta", THIN)
    poor = score_listing("Gamma", POOR)

    assert thin.colour == GREY and poor.colour == GREY
    assert "gap in reporting" in thin.verdict
    assert "unfavourable" in poor.verdict
    assert "gap in reporting" not in poor.verdict


def test_a_well_covered_favourable_listing_is_green():
    rich = score_listing("Acme", RICH)
    assert rich.colour == GREEN
    assert rich.possible >= TOTAL_POSSIBLE * 0.5


def test_green_never_claims_the_listing_will_rise():
    rich = score_listing("Acme", RICH)
    assert "not that the listing will rise" in rich.verdict
    for banned in ("will rise", "buy", "recommend", "expected return",
                   "likely to gain"):
        assert banned not in rich.verdict.replace("not that the listing will rise", "")


def test_every_card_says_it_did_not_read_the_prospectus():
    """A number out of 100 next to a company name feels like research. It is a
    reading of press coverage."""
    for text in (RICH, THIN, POOR):
        card = score_listing("X", text).render_text()
        assert "not of the prospectus" in card
        assert "no base rate" in card


def test_a_negative_signal_outranks_a_positive_one_on_the_same_test():
    """'profitable but losses widened' is not a clean yes."""
    mixed = score_listing("X", "The company is profitable but losses widened "
                               "sharply this year.")
    profit = next(r for r in mixed.results if r.key == "profitability")
    assert profit.observed and not profit.favourable


def test_the_tests_are_fixed_and_weighted():
    """Fixed criteria applied identically is what makes scores comparable."""
    assert len(TESTS) == 10
    assert TOTAL_POSSIBLE == 100
    keys = [k for k, *_r in TESTS]
    assert len(keys) == len(set(keys))


def test_coverage_is_reported_not_hidden():
    rich = score_listing("Acme", RICH)
    thin = score_listing("Beta", THIN)
    assert rich.coverage > thin.coverage
    assert "could be answered" in rich.render_text()


# ------------------------------------------------------------- routing

class _Article:
    def __init__(self, title, summary="", source="Economic Times"):
        self.title, self.summary, self.source = title, summary, source


def test_only_listing_stories_are_scored():
    assert from_article(_Article("Acme Industries IPO opens Monday")) is not None
    assert from_article(_Article("Acme lists on NSE at a premium")) is not None
    assert from_article(_Article("Reserve Bank holds rates steady")) is None


def test_the_company_name_is_extracted_from_the_headline():
    card = from_article(_Article("Acme Industries IPO opens Monday", RICH))
    assert card is not None
    assert "Acme Industries" in card.name
    assert "IPO" not in card.name


@pytest.mark.parametrize("headline", ["Beta Ltd files DRHP with Sebi",
                                      "Gamma Corp public issue to open",
                                      "Delta debut on the bourses"])
def test_listing_language_is_recognised(headline):
    assert from_article(_Article(headline)) is not None
