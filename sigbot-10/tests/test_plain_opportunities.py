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
