"""Tests for the listing scorer.

The design question was whether to score all ten tests when the coverage speaks
to three. It does not: unobserved criteria leave the denominator rather than
being filled with a neutral value, because 60/100 reads as a judgement and
"34 of a possible 41" reads as what it is.
"""
from __future__ import annotations

from datetime import date

import pytest

from sigbot.listings import (
    GREEN, GREY, TESTS, TOTAL_POSSIBLE, from_article, score_listing,
)

# Every fixture states a window now: without dates a card is correctly grey,
# because "no date in the coverage" is a state rather than permission to treat
# an issue as open.
TODAY = date(2026, 9, 4)

RICH = ("Acme IPO opens on September 2 and closes September 6. The company "
        "turned profitable with net profit "
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
    thin = score_listing("Beta", THIN, today=TODAY)
    assert thin.possible < TOTAL_POSSIBLE * 0.35
    assert thin.scored <= thin.possible
    assert "out of a possible" in thin.render_text()
    assert "/100" not in thin.render_text()


def test_thin_coverage_and_bad_news_are_different_states():
    """Collapsing them would hide a good listing that had thin coverage on the
    day it was scanned."""
    thin = score_listing("Beta", THIN, today=TODAY)
    poor = score_listing("Gamma", POOR, today=TODAY)

    assert thin.colour == GREY and poor.colour == GREY
    assert "gap in reporting" in thin.verdict
    assert "unfavourable" in poor.verdict
    assert "gap in reporting" not in poor.verdict


def test_a_well_covered_favourable_listing_is_green():
    rich = score_listing("Acme", RICH, today=TODAY)
    assert rich.colour == GREEN
    assert rich.possible >= TOTAL_POSSIBLE * 0.5


def test_green_never_claims_the_listing_will_rise():
    rich = score_listing("Acme", RICH, today=TODAY)
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
    rich = score_listing("Acme", RICH, today=TODAY)
    thin = score_listing("Beta", THIN, today=TODAY)
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
                                      "Delta IPO subscription opens"])
def test_listing_language_is_recognised(headline):
    assert from_article(_Article(headline)) is not None


# ------------------------------------------------------------- timing

FULL = ("{} IPO {}. The company turned profitable with net profit of Rs 210 "
        "crore; revenue grew 34% CAGR. Fresh issue funds capex and debt "
        "repayment. Anchor investors include mutual funds. Reasonably priced. "
        "Kotak and Axis Capital are lead managers. Oversubscribed.")


def test_a_closed_issue_is_grey_however_good_its_case():
    """'Acme IPO opens Monday' read on Thursday is a closed issue described as
    an opportunity, and the card looked identical whether the window was open,
    shut, or three weeks away."""
    from sigbot.listings import GREY, score_listing

    card = score_listing("Acme", FULL.format(
        "Acme", "opened September 1, closes 3 September"), today=TODAY)

    assert card.scored == card.possible, "the case itself is still perfect"
    assert card.colour == GREY
    assert "Closed 1 day(s) ago" in card.verdict
    assert "nothing to act on" in card.verdict


def test_an_open_issue_keeps_its_colour_and_shows_the_window():
    from sigbot.listings import GREEN, score_listing

    card = score_listing("Beta", FULL.format(
        "Beta", "opens on September 2 and closes September 6"), today=TODAY)
    assert card.colour == GREEN
    assert "Open since 02 Sep, closes 06 Sep" in card.render_text()


def test_an_upcoming_issue_says_how_many_days_away():
    from sigbot.listings import score_listing

    card = score_listing("Gamma", FULL.format(
        "Gamma", "opens on September 8 and closes September 10"), today=TODAY)
    assert card.window is not None
    assert card.window.state == "upcoming"
    assert "Opens in 4 day(s)" in card.window.note


def test_the_last_day_is_called_out():
    from sigbot.listings import score_listing

    card = score_listing("Delta", FULL.format(
        "Delta", "opens 2 September, closes 4 September"), today=TODAY)
    assert card.window is not None
    assert card.window.state == "last day"
    assert "Last day" in card.verdict


def test_no_dates_means_not_actionable_rather_than_assumed_live():
    """Absence of a date is a state, not permission to treat it as open."""
    from sigbot.listings import GREY, score_listing

    card = score_listing("Epsilon", FULL.format(
        "Epsilon", "files DRHP with Sebi"), today=TODAY)
    assert card.colour == GREY
    assert card.window is not None and card.window.state == "unknown"
    assert "Check before assuming it is live" in card.verdict


def test_timing_appears_above_the_score():
    """A complete case on a closed issue is not an opportunity, and putting the
    score first invites reading it as one."""
    from sigbot.listings import score_listing

    text = score_listing("Acme", FULL.format(
        "Acme", "opened September 1, closes 3 September"), today=TODAY
    ).render_text()
    assert text.index("Closed 1 day(s) ago") < text.index("out of a possible")


def test_a_january_issue_reported_in_december_is_next_year():
    """The year is inferred, not read — articles rarely give one, and a naive
    assumption puts a January date eleven months in the past."""
    from sigbot.listings import read_window

    window = read_window("opens on January 8 and closes January 12",
                         today=date(2026, 12, 20))
    assert window.opens is not None and window.opens.year == 2027
    assert window.state == "upcoming"


def test_listings_sort_by_how_soon_they_matter():
    """A card you can still act on is worth more than a better-scored one that
    shut yesterday. Sorting by score alone put the closed issue first."""
    from sigbot.listings import by_urgency, score_listing

    fmt = ("{} IPO {}. profitable, revenue grew, fresh issue, anchor "
           "investors, reasonably priced, Kotak, oversubscribed.")
    cards = [score_listing(name, fmt.format(name, phrase), today=TODAY)
             for name, phrase in (
                 ("CLOSED", "opened September 1, closes 3 September"),
                 ("SOON", "opens on September 8 and closes September 10"),
                 ("LASTDAY", "opens 2 September, closes 4 September"))]

    order = [c.name for c in by_urgency(cards)]
    assert order[0] == "LASTDAY"
    assert order[-1] == "CLOSED"


def test_the_date_lookup_is_silent_without_keys(monkeypatch):
    """Without GOOGLE_CSE_KEY and GOOGLE_CSE_ID the lookup returns None and the
    age-out rule remains the only defence — guessing a window would be worse
    than admitting not to know one."""
    monkeypatch.delenv("GOOGLE_CSE_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)

    from sigbot.listings import lookup_window

    assert lookup_window("Deepa Jewellers") is None


def test_the_date_lookup_reads_a_window_from_snippets(monkeypatch):
    import json

    from sigbot.listings import lookup_window

    monkeypatch.setenv("GOOGLE_CSE_KEY", "k")
    monkeypatch.setenv("GOOGLE_CSE_ID", "c")

    class _Resp:
        def read(self):
            return json.dumps({"items": [{
                "title": "Acme IPO details",
                "snippet": "Acme IPO opens on September 8 and closes "
                           "September 10, price band fixed."}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10: _Resp())

    window = lookup_window("Acme", today=TODAY)
    assert window is not None and window.state == "upcoming"


def test_relative_words_anchor_to_the_reference_date():
    """"Closes today" in Tuesday's article means Tuesday. Read against the real
    today it silently shifts every relative deadline forward each time the card
    is looked at — the Deepa case, where "allotment likely today" sat undated
    while the issue closed."""
    from datetime import date

    from sigbot.listings import read_window

    published = date(2026, 9, 1)
    window = read_window("Deepa Jewellers IPO allotment likely today: GMP "
                         "signals 11% listing gain", today=published)
    assert window.closes == published
    assert window.state in ("last day", "closed")

    late = read_window("Deepa Jewellers IPO allotment likely today",
                       today=date(2026, 9, 4))
    # Reading the same text days later must not resurrect it as live for a
    # NEW day — the caller passes the publication date, so this stays Sept 4's
    # own last day only if the article was published Sept 4.
    assert late.closes == date(2026, 9, 4)


def test_closes_tomorrow_is_one_day_out():
    from datetime import date

    from sigbot.listings import read_window

    window = read_window("Acme IPO closes tomorrow", today=date(2026, 9, 1))
    assert window.closes == date(2026, 9, 2)
    assert window.state == "upcoming" or window.state == "open" or \
           window.state == "unknown" or window.state == "last day"


def test_an_expired_relative_card_is_dropped_via_its_publication_date(tmp_path):
    """The stored card carries its source's date; "today" resolves against
    that, so a five-day-old "closes today" is correctly closed."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace as N

    from sigbot.plain_opportunities import expired

    old = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
    assert expired(N(title="Deepa Jewellers IPO GMP",
                     summary="allotment likely today: GMP signals 11% gain",
                     verdict="", sources=[f"The Economic Times ({old})"]))
