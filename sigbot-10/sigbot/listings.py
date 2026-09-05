"""Scoring a new listing on ten fixed tests — and saying what it could not test.

You asked for a model that reads a company's workings, its reports and filings,
and rates it out of 100. This is the part of that which can be done honestly,
and the difference matters.

## What this reads, and what it does not

It reads news: headlines and summaries from the listings feeds. It does not
read a DRHP, a balance sheet, an auditor's note or a cash-flow statement.
Nothing in this system can. So a criterion about profitability is not scored
from the accounts — it is scored from whether reporting mentions profitability,
which is a much weaker thing, and the card says so.

The ten tests below are fixed and applied identically to every listing. That
part of your idea is right and is what makes scores comparable. What would have
been wrong is scoring all ten when the source speaks to three: the missing
seven would be filled with a neutral value, the total would look like 60, and
60 out of a possible 100 reads as a judgement rather than as an absence.

So: unobserved criteria are excluded from the denominator, not neutralised. A
listing scored on three tests reports "34 out of a possible 41", never 34/100.
The gap is the point.

## What the colour means

The same thing it means on the Ideas tab, and not what it means on the Board.
There, green is a measured record of checked predictions. Here nothing has been
checked and nothing can be — a listing happens once, so there is no base rate to
compare a new one against.

    green   most of the heavy criteria are observable and favourable
    amber   the observable part looks reasonable, key tests unanswered
    grey    what can be seen is unfavourable, or too little can be seen

Green is not "buy". It means the observable case is complete enough to be worth
your own reading of the prospectus.

Honest constraint: grey-because-unfavourable and grey-because-invisible are
different states and the card distinguishes them, because collapsing them would
hide a good listing that simply had thin coverage on the day it was scanned.

Largest risk: that a number out of 100 attached to a company name feels like
research. It is a reading of press coverage. The disclaimer is on every card and
a test fails if it is removed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

GREEN, AMBER, GREY = "#00e676", "#ffd93d", "#8b8b9a"

# (key, weight, question, positive patterns, negative patterns)
# Weights reflect how much each answers "is this worth my time reading further",
# not how much it predicts a first-day pop — nothing here predicts that.
TESTS: list[tuple[str, int, str, tuple[str, ...], tuple[str, ...]]] = [
    ("profitability", 14, "Does reporting say it makes money?",
     ("profitable", "profit after tax", "net profit", "pat rose", "pat grew",
      "positive ebitda", "profit grew"),
     ("loss-making", "net loss", "losses widened", "yet to turn profitable",
      "cash burn", "accumulated losses")),
    ("revenue_growth", 12, "Is revenue growing?",
     ("revenue grew", "revenue rose", "revenue up", "topline growth",
      "sales grew", "cagr"),
     ("revenue fell", "revenue declined", "sales dropped", "degrowth")),
    ("issue_purpose", 12, "Does the money go into the business?",
     ("fresh issue", "expansion", "capex", "debt repayment", "working capital",
      "new capacity"),
     ("entirely offer for sale", "pure ofs", "wholly offer for sale",
      "promoters selling", "no fresh issue")),
    ("valuation_comment", 11, "Is the price being called reasonable?",
     ("reasonably priced", "attractively priced", "fairly valued",
      "discount to peers", "lower p/e"),
     ("expensive", "richly valued", "aggressively priced", "steep valuation",
      "premium to peers", "overvalued")),
    ("anchor_quality", 10, "Did serious institutions take an allocation?",
     ("anchor investors", "anchor book", "mutual funds", "sovereign fund",
      "insurance companies", "fii"),
     ("no anchor", "anchor book undersubscribed")),
    ("subscription", 10, "Is the book filling?",
     ("oversubscribed", "subscribed", "times subscribed", "strong demand",
      "fully subscribed"),
     ("undersubscribed", "weak response", "tepid demand", "extended the issue",
      "muted subscription")),
    ("lead_managers", 8, "Are the bankers established?",
     ("kotak", "icici securities", "axis capital", "jm financial", "morgan",
      "goldman", "citigroup", "nomura", "sbi capital", "iifl"),
     ()),
    ("governance", 8, "Any governance flag in the coverage?",
     ("independent directors", "board strengthened"),
     ("related party", "promoter pledge", "sebi notice", "auditor qualified",
      "regulatory action", "investigation", "resigned abruptly")),
    ("sector_tailwind", 8, "Is the sector being described as growing?",
     ("fast-growing sector", "structural tailwind", "rising demand",
      "government push", "pli scheme"),
     ("declining sector", "cyclical downturn", "oversupply",
      "shrinking market")),
    ("lock_in_overhang", 7, "Is a supply overhang coming?",
     ("long lock-in", "promoter retains"),
     ("lock-in expiry", "pre-ipo investors exit", "large ofs component",
      "early investors selling")),
]

TOTAL_POSSIBLE = sum(weight for _k, weight, *_r in TESTS)


@dataclass
class TestResult:
    key: str
    weight: int
    question: str
    observed: bool
    favourable: bool | None = None
    evidence: str = ""


@dataclass
class ListingScore:
    name: str
    scored: int
    possible: int
    colour: str
    verdict: str
    results: list[TestResult] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.possible / TOTAL_POSSIBLE if TOTAL_POSSIBLE else 0.0

    def render_text(self) -> str:
        lines = [f"NEW LISTING — {self.name}", "",
                 f"{self.scored} out of a possible {self.possible} "
                 f"({self.coverage:.0%} of the tests could be answered)", "",
                 self.verdict, ""]
        good = [r for r in self.results if r.observed and r.favourable]
        bad = [r for r in self.results if r.observed and not r.favourable]
        unseen = [r for r in self.results if not r.observed]
        if good:
            lines += ["In its favour:"] + [f"  · {r.question} yes" for r in good[:5]]
        if bad:
            lines += ["", "Against it:"] + [f"  · {r.question} no" for r in bad[:5]]
        if unseen:
            lines += ["", "The coverage did not say:"] + \
                     [f"  · {r.question}" for r in unseen[:5]]
        if self.sources:
            lines += ["", "From: " + "; ".join(self.sources[:2])]
        lines += ["", "This is a reading of press coverage, not of the "
                  "prospectus. Nothing here has been checked against how any "
                  "listing actually performed, and a single listing has no "
                  "base rate to be checked against."]
        return "\n".join(lines)


def _mentions(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        if re.search(rf"\b{re.escape(pattern)}", text):
            return pattern
    return ""


def score_listing(name: str, text: str, sources: list[str] | None = None) -> ListingScore:
    """Apply all ten tests. Unobserved criteria leave the denominator, not the
    numerator — scoring them neutral would turn silence into a middling verdict.
    """
    body = text.lower()
    results: list[TestResult] = []
    earned = possible = 0

    for key, weight, question, good, bad in TESTS:
        hit_bad = _mentions(body, bad)
        hit_good = _mentions(body, good)
        if not hit_bad and not hit_good:
            results.append(TestResult(key, weight, question, observed=False))
            continue
        # A negative signal outranks a positive one on the same criterion: an
        # article saying "profitable but losses widened" is not a clean yes.
        favourable = bool(hit_good) and not hit_bad
        possible += weight
        if favourable:
            earned += weight
        results.append(TestResult(key, weight, question, True, favourable,
                                  hit_good or hit_bad))

    colour, verdict = _band(earned, possible)
    return ListingScore(name, earned, possible, colour, verdict, results,
                        sources or [])


def _band(earned: int, possible: int) -> tuple[str, str]:
    if possible < TOTAL_POSSIBLE * 0.35:
        return GREY, (f"Only {possible} points' worth of the ten tests could be "
                      f"answered from the coverage. That is too little to say "
                      "anything — it is a gap in reporting, not a judgement on "
                      "the company.")
    share = earned / possible if possible else 0.0
    if share >= 0.70:
        return GREEN, (f"{earned} of the {possible} points that could be judged "
                       "came out favourable. That means the observable case is "
                       "complete enough to be worth reading the prospectus "
                       "yourself — not that the listing will rise.")
    if share >= 0.45:
        return AMBER, (f"{earned} of {possible} favourable. Mixed on what can be "
                       "seen, and the tests below that went unanswered are the "
                       "ones that would settle it.")
    return GREY, (f"Only {earned} of {possible} judgeable points came out "
                  "favourable. What can be seen is unfavourable — which is a "
                  "different thing from thin coverage, and worth separating.")


def from_article(article) -> ListingScore | None:
    """Score a news item if it looks like it concerns a listing."""
    title = getattr(article, "title", "") or ""
    summary = getattr(article, "summary", "") or ""
    body = f"{title} {summary}"
    if not re.search(r"\b(ipo|listing|lists on|debut|public issue|drhp|rhp)\b",
                     body, re.I):
        return None

    name = re.split(r"\b(ipo|listing|files|opens|debut)\b", title, flags=re.I)[0]
    name = name.strip(" -–—:,") or title[:60]
    source = getattr(article, "source", "")
    return score_listing(name, body, [source] if source else [])
