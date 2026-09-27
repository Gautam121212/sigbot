"""Ideas must be resolvable — no news-headline cards that never finish."""
from sigbot.report import _live_ideas


def test_unresolvable_news_headlines_are_dropped():
    """A news-thesis card with no window and nothing answered can never finish —
    it must not appear (it would sit 'unfinished' forever and age out unchecked)."""
    data = {"opportunities": [
        {"kind": "Market thesis", "summary": "Senate rejects Iran resolution",
         "answered": [], "unanswered": ["q1", "q2", "q3"]},
        {"kind": "Market thesis", "summary": "Oil drops 3%",
         "answered": [], "unanswered": ["q1", "q2"]},
    ]}
    assert _live_ideas(data) == []          # both dropped — unresolvable


def test_a_resolvable_idea_is_kept():
    """An idea that has answered part of its case (real progress toward a
    verifiable outcome) is kept."""
    data = {"opportunities": [
        {"kind": "New listing", "summary": "Varmora Granito",
         "answered": ["q1", "q2"], "unanswered": ["q3"]},
    ]}
    assert len(_live_ideas(data)) == 1      # kept — it can resolve


def test_no_opportunities_is_empty():
    assert _live_ideas({"opportunities": []}) == []
    assert _live_ideas({}) == []
