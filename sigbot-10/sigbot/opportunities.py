"""Model D — opportunity digest (IPOs, macro dislocations, thematic ideas).

This module deliberately does not produce a confidence score, and that is the
main design decision in it.

Why. A score has to come from somewhere. Models B and C get theirs from
thousands of resolved historical observations. This one cannot:

  * IPOs are roughly 200–300 a year in the US, each one structurally unique,
    and the "growth plans" you would score are the S-1 and the underwriter's
    marketing — written by people paid to make it sound good. The sample is
    small and the inputs are adversarial.
  * Macro dislocation theses ("property is cheap in X because of conflict")
    are n=1. There is no population of comparable events to compute a
    frequency over. Attaching "80% confidence" to one would be a number with
    no denominator.

So this produces a structured thesis card instead: the claim, the mechanism,
what would have to be true, what would falsify it, and what you cannot
currently observe. The purpose is to make a weak idea look weak on the page
rather than to dress it as a signal.

If you want this scored, the requirement is explicit and listed in
`SCORING_REQUIREMENTS` below. It is a data-acquisition problem, not a
modelling one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from .providers.news import dedupe, source_quality
from .types import Article

SCORING_REQUIREMENTS = {
    "ipo": [
        "historical IPO dataset with pricing date, offer price, first-day close, "
        "and 3/6/12-month returns, at least 15 years deep",
        "point-in-time S-1 text so the thesis inputs are the ones that existed "
        "at pricing, not the post-hoc narrative",
        "matched control group of non-IPO peers to separate IPO effect from "
        "sector drift",
    ],
    "macro": [
        "a defined population of comparable historical dislocations "
        "(conflict, sanctions, currency shock) with measurable entry and exit",
        "an investable, priced instrument — not a spot asset you cannot exit",
        "transaction, holding and repatriation costs, which usually dominate "
        "the thesis in illiquid real assets",
    ],
}

IPO_PATTERNS = re.compile(
    r"\b(ipo|initial public offering|files? to go public|s-1|prospectus|"
    r"direct listing|lists? on (the )?(nasdaq|nyse|lse|nse|bse))\b", re.I
)
MACRO_PATTERNS = re.compile(
    r"\b(sanction\w*|conflict|war|ceasefire|devalu\w+|capital controls?|"
    r"rate cut|rate hike|default|bailout|embargo|tariff\w*|nationalis\w+|"
    r"property (price|market)|real estate (price|market))\b", re.I
)


@dataclass
class ThesisCard:
    category: str                    # "ipo" | "macro"
    subject: str
    claim: str
    mechanism: str
    articles: list[Article]
    must_be_true: list[str] = field(default_factory=list)
    would_falsify: list[str] = field(default_factory=list)
    unobservable: list[str] = field(default_factory=list)
    source_strength: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def render(self) -> str:
        lines = [
            f"[{self.category.upper()}] {self.subject}",
            f"Claim: {self.claim}",
            f"Mechanism: {self.mechanism}",
            "Confidence: NONE. This model has no backtest and no resolved "
            "observations. It surfaces candidates; it does not rate them.",
            f"Source strength: {self.source_strength:.2f}",
        ]
        if self.must_be_true:
            lines.append("Must be true:")
            lines += [f"  · {x}" for x in self.must_be_true]
        if self.would_falsify:
            lines.append("Would falsify:")
            lines += [f"  · {x}" for x in self.would_falsify]
        if self.unobservable:
            lines.append("Cannot currently observe:")
            lines += [f"  · {x}" for x in self.unobservable]
        for a in self.articles[:2]:
            lines.append(f"  → {a.title[:110]} ({a.source}, {a.published_at:%Y-%m-%d})")
        return "\n".join(lines)


DEFAULT_CHECKS = {
    "ipo": (
        [
            "the business was already profitable, or has a credible dated path to it",
            "insider lock-up expiry is far enough out that supply is not the story",
            "the raise funds growth rather than paying down pre-IPO debt or cashing out holders",
        ],
        [
            "pricing above the indicated range on retail demand alone",
            "revenue growth decelerating in the last reported quarter",
            "a share class structure that leaves outside holders with no vote",
        ],
        [
            "true free float after lock-up expiry",
            "whether anchor investors are locked or flipping",
            "unit economics at the segment level, which the S-1 usually aggregates away",
        ],
    ),
    "macro": (
        [
            "the asset is genuinely priced lower in real terms, not just in a "
            "depreciating local currency",
            "there is a liquid, legal exit available to a non-resident",
            "the dislocation has a plausible resolution path with a timeframe",
        ],
        [
            "the discount is smaller than transaction, holding and repatriation costs",
            "prices already recovered before the story was published",
            "the risk that caused the discount is still escalating rather than peaking",
        ],
        [
            "actual transacted prices, as opposed to quoted asking prices",
            "how much of the discount is a currency effect versus an asset effect",
            "whether foreign ownership rules change under stress",
        ],
    ),
}


def _subject_from(title: str, category: str) -> str:
    if category == "ipo":
        m = re.match(r"^([A-Z][\w&.\- ]{2,40}?)\s+(files|prices|sets|launches|plans)", title)
        if m:
            return m.group(1).strip()
    words = [w for w in title.split() if w[:1].isupper()]
    return " ".join(words[:4]) or title[:40]


class OpportunityModel:
    """Turns news into thesis cards. Emits no probabilities, by design."""

    def __init__(self, min_source_quality: float = 0.6):
        self.min_source_quality = min_source_quality

    def scan(self, articles: Sequence[Article]) -> list[ThesisCard]:
        cards: list[ThesisCard] = []
        for cluster in dedupe(articles):
            lead = cluster[0]
            quality = source_quality(lead.source)
            if quality < self.min_source_quality:
                continue
            text = f"{lead.title} {lead.summary}"

            category = None
            if IPO_PATTERNS.search(text):
                category = "ipo"
            elif MACRO_PATTERNS.search(text):
                category = "macro"
            if category is None:
                continue

            must, falsify, unobs = DEFAULT_CHECKS[category]
            corroboration = min(1.0, 0.7 + 0.1 * (len(cluster) - 1))
            cards.append(
                ThesisCard(
                    category=category,
                    subject=_subject_from(lead.title, category),
                    claim=lead.title.strip(),
                    mechanism=(lead.summary[:220].strip() or
                               "not stated in the source; treat the headline as the whole claim"),
                    articles=cluster[:3],
                    must_be_true=list(must),
                    would_falsify=list(falsify),
                    unobservable=list(unobs),
                    source_strength=round(quality * corroboration, 2),
                )
            )
        return cards


def render_digest(cards: Sequence[ThesisCard], jurisdiction_note: str = "") -> str:
    if not cards:
        return "Opportunity digest: nothing matched IPO or macro-dislocation patterns."
    header = [
        f"Opportunity digest — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        f"{len(cards)} candidate(s). None carry a confidence score; see each card.",
    ]
    body = [c.render() for c in cards]
    tail = [jurisdiction_note] if jurisdiction_note else []
    return "\n\n".join(header + body + tail)
