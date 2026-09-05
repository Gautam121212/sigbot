"""Tests for the plain-language opportunity cards.

The digest used to read like a research memo — source strength 0.49, gap type,
ceiling, enrich(). These check it reads like something you would act on, and
that the colours never overstate what they know.
"""
from __future__ import annotations

from datetime import datetime, timezone


from sigbot.opportunities import ThesisCard
from sigbot.plain_opportunities import (
    AMBER, GREEN, GREY, PLAIN, from_candidate, from_thesis, render_plain,
)
from sigbot.venture import PLAN_THRESHOLD, RUBRIC
from sigbot.venture_news import NewsCandidate, OpportunityScore


def _candidate(overrides=None, unknown=()):
    scores = {k: 5 for k in RUBRIC}
    scores.update(overrides or {})
    opp = OpportunityScore(title="A thing", thesis="Something changed.",
                           trigger="News", scores=scores, notes={},
                           sources=["Reuters"],
                           created_at=datetime.now(timezone.utc))
    return NewsCandidate(opportunity=opp, gap_type="supply_chain_shift",
                         needs_enrichment=list(unknown))


def _thesis(strength=0.9):
    return ThesisCard(category="MACRO", subject="Fed", claim="Fears overblown.",
                      mechanism="not stated", articles=["Reuters"],
                      must_be_true=["the discount is real"], would_falsify=[],
                      unobservable=[], source_strength=strength,
                      created_at=datetime.now(timezone.utc))


# ------------------------------------------------------------ plain language

def test_no_jargon_reaches_the_reader():
    card = from_candidate(_candidate(unknown=["distribution", "skill_fit"]))
    text = card.render_text().lower()
    for term in ("rubric", "enrich", "ceiling", "gap_type", "source_strength",
                 "needs_enrichment", "threshold"):
        assert term not in text, f"{term!r} leaked into the card"


def test_the_banner_says_what_kind_of_thing_it_is():
    assert from_candidate(_candidate()).kind == "Supply chain change"
    assert from_thesis(_thesis()).kind == "Macro / economy"


def test_money_is_described_never_invented():
    """`capital_required` is a score, not a figure. No rupee amount exists."""
    cheap = from_candidate(_candidate({"capital_required": 9}))
    dear = from_candidate(_candidate({"capital_required": 2}))
    unknown = from_candidate(_candidate(unknown=["capital_required"]))

    assert cheap.money == PLAIN["capital_required"][1]
    assert dear.money == PLAIN["capital_required"][2]
    assert "would have to work it out" in unknown.money
    for card in (cheap, dear, unknown):
        assert "₹" not in card.money and "$" not in card.money


# ---------------------------------------------------------------- colours

def test_a_complete_case_is_green():
    card = from_candidate(_candidate({k: 10 for k in RUBRIC}))
    assert card.colour == GREEN
    assert "not the same as a good idea" in card.verdict, (
        "green must not imply the opportunity is likely to work")


def test_an_unreachable_case_is_grey():
    card = from_candidate(_candidate({k: 1 for k in RUBRIC}))
    assert card.colour == GREY
    assert "Cannot get there" in card.verdict


def test_an_open_case_is_amber_and_lists_the_questions():
    card = from_candidate(_candidate({k: 8 for k in RUBRIC},
                                     unknown=["distribution", "skill_fit"]))
    if card.colour == AMBER:
        assert "not yet worth time" in card.verdict
    assert card.unanswered, "an unknown must produce a question to answer"
    assert any("reach a buyer" in q for q in card.unanswered)


def test_colour_never_claims_to_predict():
    """Board colours mean a measured record. Nothing like that exists here."""
    for card in (from_candidate(_candidate({k: 10 for k in RUBRIC})),
                 from_candidate(_candidate({k: 1 for k in RUBRIC})),
                 from_thesis(_thesis())):
        assert not any(w in card.verdict.lower()
                       for w in ("likely", "probability", "will rise",
                                 "expected return", "confident"))


def test_weak_sourcing_is_called_out():
    weak = from_thesis(_thesis(0.3))
    assert weak.colour == GREY and "Weak sourcing" in weak.verdict
    strong = from_thesis(_thesis(0.9))
    assert strong.colour == AMBER
    assert "never been scored against outcomes" in strong.verdict


# ----------------------------------------------------------------- digest

def test_unknowns_come_from_needs_enrichment_not_missing_keys():
    """Every criterion is always scored — a missing key raises. An earlier
    version looked for absent keys and would have found no unknowns at all."""
    card = from_candidate(_candidate(unknown=["distribution",
                                              "time_to_first_revenue"]))
    assert len(card.unanswered) >= 2
    plain_card = from_candidate(_candidate())
    assert plain_card.unanswered == []


def test_the_digest_orders_by_completeness_and_ends_honestly():
    text = render_plain([_thesis(0.9)],
                        [_candidate({k: 10 for k in RUBRIC}),
                         _candidate({k: 1 for k in RUBRIC})])
    assert text.index("Complete enough") < text.index("Cannot get there")
    assert "not how likely it is to work" in text
    assert "single events never can be" in text


def test_an_empty_scan_produces_nothing():
    assert render_plain([], []) == ""


def test_the_threshold_quoted_matches_the_rubric():
    card = from_candidate(_candidate({k: 1 for k in RUBRIC}))
    assert f"{PLAN_THRESHOLD:.0f}" in card.verdict


# ------------------------------------------------------------- the app tab

def _tiny_report(opportunities, tmp_path):
    from sigbot.export_app import build_export
    from sigbot.report import build_report

    data = build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"), opportunities=opportunities)
    return build_report(data)


def test_the_ideas_tab_exists_and_links(tmp_path):
    from sigbot.export_app import build_opportunities

    opps = build_opportunities([_thesis()], [_candidate()])
    html = _tiny_report(opps, tmp_path)

    assert 'href="#ideas"' in html and 'id="ideas"' in html
    for i in range(len(opps)):
        assert f'id="i-{i}"' in html, "a card has no detail page"


def test_the_tab_has_no_javascript(tmp_path):
    """The whole report opens from Files on an iPhone because it has none."""
    from sigbot.export_app import build_opportunities

    html = _tiny_report(build_opportunities([_thesis()], [_candidate()]), tmp_path)
    assert "<script" not in html.lower()


def test_the_card_shows_money_and_the_open_questions(tmp_path):
    from sigbot.export_app import build_opportunities

    opps = build_opportunities([], [_candidate({"capital_required": 2},
                                               unknown=["distribution"])])
    html = _tiny_report(opps, tmp_path)
    assert "Money" in html
    assert "needs real capital before any revenue" in html
    assert "You would have to find out" in html


def test_the_tab_says_what_the_colours_do_not_mean(tmp_path):
    """Board colours mean a measured record. These do not, and the page must
    say so or the two get read the same way."""
    from sigbot.export_app import build_opportunities

    html = _tiny_report(build_opportunities([_thesis()], []), tmp_path)
    assert "never how likely it is to work" in html
    assert "not a signal" in html


def test_an_empty_scan_renders_a_calm_page(tmp_path):
    """Empty is the normal state and must not look like a fault."""
    html = _tiny_report([], tmp_path)
    assert 'id="ideas"' in html
    assert "Nothing new" in html and "every four hours" in html


def test_a_broken_card_is_skipped_not_fatal(tmp_path):
    from sigbot.export_app import build_opportunities

    class Broken:
        title = "boom"

        def __getattr__(self, name):
            raise ValueError("malformed")

    opps = build_opportunities([], [Broken(), _candidate()])
    assert len(opps) == 1, "one bad card took the whole scan down"


# --------------------------------------- one source of truth for both outputs

def test_publish_reads_the_store_rather_than_rescanning(tmp_path, monkeypatch):
    """The app and the message must not disagree.

    `run_publish` used to run its own RSS fetch. Two fetches minutes apart
    return different articles, so the message could carry two cards while the
    app rendered an empty tab — the same event with two answers, and nothing on
    screen explaining the difference.
    """
    import os

    from sigbot.runner import _read_opportunity_store, _write_opportunity_store

    monkeypatch.chdir(tmp_path)
    assert _read_opportunity_store() == [], "an absent store is not an error"

    _write_opportunity_store([], [_candidate({"demand_evidence": 9})])
    stored = _read_opportunity_store()
    assert len(stored) == 1
    assert stored[0]["title"] and stored[0]["colour"] and stored[0]["money"]
    assert os.path.exists("opportunities.json")


def test_a_corrupt_store_yields_nothing_rather_than_raising(tmp_path, monkeypatch):
    from sigbot.runner import _read_opportunity_store

    monkeypatch.chdir(tmp_path)
    (tmp_path / "opportunities.json").write_text("{not json")
    assert _read_opportunity_store() == []


def test_the_store_holds_what_the_app_renders(tmp_path, monkeypatch):
    """Whatever is written must be exactly what build_opportunities produces,
    or the app and the message would format the same card differently."""
    from sigbot.export_app import build_opportunities
    from sigbot.runner import _read_opportunity_store, _write_opportunity_store

    monkeypatch.chdir(tmp_path)
    candidate = _candidate({"demand_evidence": 9}, unknown=["distribution"])
    _write_opportunity_store([], [candidate])
    assert _read_opportunity_store() == build_opportunities([], [candidate])


def test_listings_reach_the_page_not_only_telegram(tmp_path, monkeypatch):
    """Listings were sent to Telegram and never written to the store, so an IPO
    card arrived on your phone and was absent from the page — the two views
    disagreeing about what exists, which is the failure this store was created
    to prevent."""
    from datetime import date

    from sigbot.listings import score_listing
    from sigbot.runner import _read_opportunity_store, _write_opportunity_store

    monkeypatch.chdir(tmp_path)
    card = score_listing(
        "Acme",
        "Acme IPO opens on September 2 and closes September 6. Profitable, "
        "revenue grew, fresh issue, anchor investors, reasonably priced, Kotak.",
        ["Economic Times"], today=date(2026, 9, 4))

    _write_opportunity_store([], [], [card])
    rows = _read_opportunity_store()

    assert len(rows) == 1
    assert rows[0]["kind"] == "New listing"
    assert rows[0]["colour"] == card.colour
    assert "Open since 02 Sep" in rows[0]["summary"]
    assert "ten tests" in rows[0]["money"]


def test_a_closed_listing_reaches_the_page_grey(tmp_path, monkeypatch):
    """'This scored well and you missed it' is worth knowing, so it is stored —
    but it must carry its grey, not a live colour."""
    from datetime import date

    from sigbot.listings import GREY, score_listing
    from sigbot.runner import _read_opportunity_store, _write_opportunity_store

    monkeypatch.chdir(tmp_path)
    card = score_listing(
        "Beta",
        "Beta IPO opened September 1, closes 3 September. Profitable, revenue "
        "grew, fresh issue, anchor investors, reasonably priced, Kotak.",
        ["ET"], today=date(2026, 9, 4))

    _write_opportunity_store([], [], [card])
    row = _read_opportunity_store()[0]
    assert row["colour"] == GREY
    assert "nothing to act on" in row["verdict"]


def test_the_source_line_is_a_citation_not_a_repr():
    """str() on an Article prints the whole object — uid, summary and all —
    into the card under "Where it came from"."""
    from datetime import datetime, timezone

    from sigbot.plain_opportunities import _cite
    from sigbot.types import Article

    article = Article(uid="eb2eda53d7619789", title="t", summary="s",
                      url="http://x", source="The Economic Times",
                      published_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
                      ingested_at=datetime.now(timezone.utc))

    cited = _cite(article)
    assert cited == "The Economic Times (2026-09-03)"
    assert "uid=" not in cited
    assert "Article(" not in cited


def test_an_already_formatted_source_passes_through():
    from sigbot.plain_opportunities import _cite

    assert _cite("Reuters (2026-09-01)") == "Reuters (2026-09-01)"


def test_a_closed_idea_is_dropped():
    """Two paths produce IPO cards: the listing scorer, which reads dates, and
    the venture thesis path, which does not. So an allotment story arrived with
    no timing and sat in Ideas after the issue closed — an opportunity you
    could not take, described as one you could."""
    from types import SimpleNamespace

    from sigbot.plain_opportunities import expired

    assert expired(SimpleNamespace(
        title="Deepa Jewellers IPO GMP",
        summary="IPO opened September 1, closes 3 September.", verdict=""))


def test_an_upcoming_idea_is_kept():
    from types import SimpleNamespace

    from sigbot.plain_opportunities import expired

    assert not expired(SimpleNamespace(
        title="Kanohar Electricals IPO",
        summary="IPO to open on Sep 8; price band fixed.", verdict=""))


def test_an_idea_with_no_date_is_kept():
    """Absence of a date is not evidence that it is over, and silently
    discarding it would hide things that are still live."""
    from types import SimpleNamespace

    from sigbot.plain_opportunities import expired

    assert not expired(SimpleNamespace(
        title="Russia-Ukraine wheat",
        summary="War has been impacting global wheat prices.", verdict=""))


def test_a_stale_today_story_is_dropped():
    """'Deepa Jewellers IPO allotment likely today' contains no date at all, so
    window parsing kept it. But 'today' in a story published four days ago is
    exactly the evidence needed — and the card never carried the publication
    date."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from sigbot.plain_opportunities import expired

    now = datetime.now(timezone.utc)
    old = SimpleNamespace(
        title="Deepa Jewellers IPO GMP",
        summary="IPO allotment likely today: GMP signals 11% listing gain",
        verdict="", sources=[f"ET ({(now - timedelta(days=4)).date()})"])
    fresh = SimpleNamespace(
        title="Deepa Jewellers IPO GMP",
        summary="IPO allotment likely today: GMP signals 11% listing gain",
        verdict="", sources=[f"ET ({(now - timedelta(days=1)).date()})"])

    assert expired(old)
    assert not expired(fresh)


def test_shelf_life_is_shorter_for_time_critical_items():
    """An allotment story is worthless the day after allotment. A supply-chain
    thesis is still readable a month on."""
    from sigbot.plain_opportunities import DEFAULT_SHELF_LIFE, shelf_life

    assert shelf_life("IPO allotment today GMP") <= 2
    assert shelf_life("wheat prices supply chain") == DEFAULT_SHELF_LIFE
    assert shelf_life("IPO to open on Sep 8") <= 10


def test_a_card_with_no_publication_date_is_kept():
    """This only fires when a date is available. Absence is not evidence."""
    from types import SimpleNamespace

    from sigbot.plain_opportunities import stale

    assert not stale(SimpleNamespace(title="X", summary="IPO allotment today",
                                     sources=[]))


def test_an_ipo_thesis_is_scored_not_bookmarked():
    """An IPO thesis used to arrive as a copied headline with "look into it"
    attached — no score, no date, no judgement, which is a bookmark rather than
    an idea."""
    from datetime import datetime, timezone
    from types import SimpleNamespace as N

    from sigbot.plain_opportunities import from_thesis

    article = N(source="Economic Times",
                published_at=datetime(2026, 9, 3, tzinfo=timezone.utc))
    card = from_thesis(N(
        subject="Kanohar Electricals IPO",
        claim="Kanohar Electricals IPO to open on September 8; price band "
              "fixed at Rs 601-632. The company is profitable with revenue "
              "growth. Kotak is lead manager.",
        category="market_thesis", source_strength=0.9, articles=[article]))

    assert card.kind.startswith("IPO —"), "the window belongs in the banner"
    assert "ten tests" in card.money
    assert "Opens in" in card.summary or "Open since" in card.summary


def test_the_window_state_is_the_banner():
    from datetime import datetime, timezone
    from types import SimpleNamespace as N

    from sigbot.plain_opportunities import from_thesis

    article = N(source="ET", published_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    card = from_thesis(N(
        subject="Acme IPO", claim="Acme IPO opened September 1, closes 3 "
        "September. Profitable, anchor investors, Kotak.",
        category="market_thesis", source_strength=0.9, articles=[article]))
    assert card.kind == "IPO — closed"


def test_an_undated_ipo_card_ages_out_after_two_days():
    """A listing window is days wide, so an unverifiable IPO card older than
    two days is noise either way. Undated macro theses have no such clock and
    are kept — the age rule is only for things that expire by construction."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace as N

    from sigbot.plain_opportunities import expired

    today = datetime.now(timezone.utc).date()
    old = (today - timedelta(days=5)).isoformat()

    assert expired(N(title="Deepa Jewellers IPO GMP",
                     summary="allotment likely today", verdict="",
                     sources=[f"The Economic Times ({old})"]))
    assert not expired(N(title="Wheat and the war",
                         summary="war impacting wheat prices", verdict="",
                         sources=[f"Farms.com ({old})"]))


def test_a_fresh_undated_ipo_card_is_kept():
    from datetime import datetime, timezone
    from types import SimpleNamespace as N

    from sigbot.plain_opportunities import expired

    today = datetime.now(timezone.utc).date().isoformat()
    assert not expired(N(title="Rays Belief IPO Allotment",
                         summary="allotment status online", verdict="",
                         sources=[f"IPO Watch ({today})"]))
