"""The opportunity model catches real opportunities, not only IPOs/macro."""
from datetime import datetime, timezone

from sigbot.opportunities import OpportunityModel
from sigbot.types import Article


def _mk(title):
    now = datetime.now(timezone.utc)
    return Article(uid=str(hash(title)), title=title, summary=title,
                   url=f"http://x/{abs(hash(title))}", source="reuters.com",
                   published_at=now, ingested_at=now)


def test_opportunity_headlines_produce_cards():
    """The bug: the model only matched IPO/macro and returned 0 for real
    opportunities. Now it catches incentives, new markets, funding."""
    arts = [_mk(t) for t in [
        "India opens semiconductor manufacturing incentives worth $10 billion",
        "Dubai launches free zone for AI companies with zero corporate tax",
        "Startup raises $50M to build fintech infrastructure",
        "New regulation opens $2 trillion private credit market",
    ]]
    cards = OpportunityModel().scan(arts)
    assert len(cards) >= 2, "opportunity headlines must produce thesis cards"
    assert any(c.category == "opportunity" for c in cards)


def test_plain_news_still_produces_nothing():
    """It must not fire on everything — only genuine opportunity signals."""
    arts = [_mk("Local weather stays mild through the weekend"),
            _mk("Celebrity spotted at a restaurant downtown")]
    assert OpportunityModel().scan(arts) == []
