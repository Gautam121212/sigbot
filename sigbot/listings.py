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
from datetime import date, datetime, timedelta, timezone

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



# ---------------------------------------------------------------- timing
#
# An IPO card with no dates is worse than no card. "Acme IPO opens Monday" read
# on Thursday is a closed issue described as an opportunity, and the reader has
# no way to tell — the card looked identical whether the window was open,
# shut, or three weeks away.
#
# Dates are extracted from the coverage, which is unreliable: a headline may
# give one date, both, or none. So the state is one of five, and "no date in
# the coverage" is a state rather than an assumption that it is live.

DATE_PATTERNS = (
    # "opens on September 8", "opens Sept 8", "opens 8 September"
    r"open[s]?\s+(?:on\s+)?(?P<d1>\d{1,2})\s+(?P<m1>[A-Z][a-z]{2,8})",
    r"open[s]?\s+(?:on\s+)?(?P<m2>[A-Z][a-z]{2,8})\s+(?P<d2>\d{1,2})",
)
CLOSE_PATTERNS = (
    r"clos(?:e|es|ing)\s+(?:on\s+)?(?P<d1>\d{1,2})\s+(?P<m1>[A-Z][a-z]{2,8})",
    r"clos(?:e|es|ing)\s+(?:on\s+)?(?P<m2>[A-Z][a-z]{2,8})\s+(?P<d2>\d{1,2})",
)

MONTHS = {m.lower()[:3]: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


def _find_date(text: str, patterns, today: date) -> date | None:
    """A day and month from the coverage. The year is inferred, not read.

    Articles rarely give a year, so one is assumed — this year, unless that
    puts the date more than six months in the past, in which case it is next
    year. A January issue reported in December is the case that breaks a naive
    assumption.
    """
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        groups = match.groupdict()
        day = groups.get("d1") or groups.get("d2")
        month = groups.get("m1") or groups.get("m2")
        if not day or not month:
            continue
        number = MONTHS.get(month.lower()[:3])
        if not number:
            continue
        try:
            found = date(today.year, number, int(day))
        except ValueError:
            continue
        if (today - found).days > 180:
            try:
                found = date(today.year + 1, number, int(day))
            except ValueError:
                continue
        return found
    return None


@dataclass
class Window:
    opens: date | None
    closes: date | None
    state: str            # upcoming | open | last day | closed | unknown
    note: str
    actionable: bool


def read_window(text: str, today: date | None = None) -> Window:
    """When the issue is open, as far as the coverage says."""
    today = today or datetime.now(timezone.utc).date()
    opens = _find_date(text, DATE_PATTERNS, today)
    closes = _find_date(text, CLOSE_PATTERNS, today)

    # Relative words, anchored to the reference date the caller supplies —
    # which, for a stored card, is the article's own publication date. "Closes
    # today" in Tuesday's article means Tuesday, and reading it against the
    # real today silently shifts every relative deadline forward each time the
    # card is looked at. This is the Deepa case: "allotment likely today" had
    # no absolute date to find, so the card sat undated while the issue closed.
    lowered = text.lower()
    if closes is None:
        if re.search(r"clos(?:e|es|ing)\s+today", lowered) or \
           re.search(r"(?:allotment|listing)\s+(?:likely\s+)?today", lowered):
            closes = today
        elif re.search(r"clos(?:e|es|ing)\s+tomorrow", lowered):
            closes = today + timedelta(days=1)
    if opens is None and re.search(r"open(?:s|ed)?\s+today", lowered):
        opens = today

    if opens is None and closes is None:
        return Window(None, None, "unknown",
                      "The coverage gives no dates, so whether this is open, "
                      "shut, or weeks away is not known from here. Check "
                      "before assuming it is live.", False)

    if closes and today > closes:
        gone = (today - closes).days
        return Window(opens, closes, "closed",
                      f"Closed {gone} day(s) ago, on {closes:%d %b}. Kept for "
                      "the record; there is nothing to act on.", False)
    if closes and today == closes:
        return Window(opens, closes, "last day",
                      f"Last day — closes today, {closes:%d %b}.", True)
    if opens and today < opens:
        away = (opens - today).days
        return Window(opens, closes, "upcoming",
                      f"Opens in {away} day(s), on {opens:%d %b}"
                      + (f", closes {closes:%d %b}." if closes else "."), True)
    if opens and today >= opens:
        return Window(opens, closes, "open",
                      f"Open since {opens:%d %b}"
                      + (f", closes {closes:%d %b}." if closes else "."), True)
    return Window(opens, closes, "unknown",
                  "Dates found but not readable as a window.", False)


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
    window: "Window | None" = None
    results: list[TestResult] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.possible / TOTAL_POSSIBLE if TOTAL_POSSIBLE else 0.0

    def render_text(self) -> str:
        # Timing first. A complete case on a closed issue is not an
        # opportunity, and putting the score above the date invites reading it
        # as one.
        timing = (self.window.note if self.window
                  else "No dates read from the coverage.")
        lines = [f"NEW LISTING — {self.name}", "", timing, "",
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


def score_listing(name: str, text: str, sources: list[str] | None = None,
                  today: date | None = None) -> ListingScore:
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

    window = read_window(text, today)
    colour, verdict = _band(earned, possible)

    # A closed issue is grey whatever its case looked like. The tests still
    # ran and the score is still shown, because "this one scored well and you
    # missed it" is worth knowing — but it is not a live opportunity and must
    # not wear a live colour.
    if not window.actionable:
        colour = GREY
        # Timing first, then the original verdict. An earlier version replaced
        # the verdict when no dates were found, which threw away the coverage
        # assessment — "thin reporting" and "no dates" are different facts and
        # you need both.
        verdict = f"{window.note} {verdict}"
    elif window.state == "last day":
        verdict = window.note + " " + verdict

    return ListingScore(name, earned, possible, colour, verdict, window,
                        results, sources or [])


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
    # "debut" and bare "listing" matched film premieres and EV launches.
    # A listing card needs a market word, not a synonym for "first".
    if not re.search(r"\b(ipo|public issue|drhp|rhp|price band|"
                     r"lists on (?:nse|bse|nyse|nasdaq)|"
                     r"listing gain|subscription|allotment|gmp|"
                     r"anchor investor)\b", body, re.I):
        return None

    name = re.split(r"\b(ipo|listing|files|opens|debut)\b", title, flags=re.I)[0]
    name = name.strip(" -–—:,") or title[:60]
    source = getattr(article, "source", "")
    return score_listing(name, body, [source] if source else [])


# Closing soonest first. A card you can still act on is worth more than a
# better-scored one that shut yesterday, and sorting by score alone put the
# closed issue at the top.
URGENCY = {"last day": 0, "open": 1, "upcoming": 2, "unknown": 3, "closed": 4}


def by_urgency(cards: list[ListingScore]) -> list[ListingScore]:
    """Sort by how soon it matters, then by how complete the case is."""
    return sorted(cards, key=lambda c: (
        URGENCY.get(c.window.state if c.window else "unknown", 3),
        -(c.scored / c.possible if c.possible else 0.0)))


def lookup_window(name: str, today: date | None = None) -> "Window | None":
    """Ask the web for an issue's dates when the coverage gave none.

    Uses Google's Custom Search JSON API — free at 100 queries a day, which is
    far more undated IPOs than a day produces. Runs only when GOOGLE_CSE_KEY
    and GOOGLE_CSE_ID are set; without them this returns None and the age-out
    rule remains the only defence, because guessing a window would be worse
    than admitting not to know one.
    """
    import json
    import os
    import urllib.parse
    import urllib.request

    key = os.environ.get("GOOGLE_CSE_KEY")
    engine = os.environ.get("GOOGLE_CSE_ID")
    if not key or not engine:
        return None

    query = urllib.parse.quote(f"{name} IPO open close dates")
    url = ("https://www.googleapis.com/customsearch/v1"
           f"?key={key}&cx={engine}&q={query}&num=5")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001  # handled: a failed lookup means no window, and the age-out rule still applies
        return None

    text = " ".join(
        f"{item.get('title', '')} {item.get('snippet', '')}"
        for item in payload.get("items", []))
    window = read_window(text, today)
    return window if window.state != "unknown" else None
