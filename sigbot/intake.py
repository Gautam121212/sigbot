"""The intake gate: what is allowed into the loop at all.

Every news story, idea and opportunity passes through here first, and gets
one of three verdicts — the way an experienced trader triages a feed:

    ACT     material, new, about something tradable, from a source that has
            not been proven unreliable. Enters the trading loop.
    LEARN   material but not tradable here (an earthquake, a war, a policy
            shift), or from a source whose record is poor. Recorded so its
            market reaction can be studied, never traded on.
    DROP    not new or not material: recaps of moves already made, lists,
            opinion. Never shown, never scored.

The playbook's rule behind it: the question is never whether a story is good
or bad but whether it is already in the price. A recap of a move that already
happened is, by definition, in the price. Recording it would teach the system
from noise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ACT, LEARN, DROP = "ACT", "LEARN", "DROP"

# Event classes a professional treats as potentially price-moving. Each maps
# to an event type in the event-study file where one exists, so LEARN items
# feed measured reactions rather than narrative.
MATERIAL: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "quarterly results", "q1 results", "q2 results",
                 "q3 results", "q4 results", "profit", "revenue", "guidance",
                 "outlook", "forecast cut", "forecast raise", "beats", "misses"),
    "deal": ("merger", "acquisition", "acquire", "buyout", "takeover",
             "to buy", "stake sale", "spin-off", "spinoff", "ipo", "listing"),
    "regulatory": ("fda", "approval", "approved", "ban", "probe",
                   "investigation", "lawsuit", "fine", "antitrust", "sec charges",
                   "recall", "license"),
    "credit": ("bankruptcy", "chapter 11", "default", "downgrade", "upgrade",
               "rating cut", "insolvency", "restructuring"),
    "macro": ("rate cut", "rate hike", "interest rate", "central bank", "fed ",
              "rbi", "ecb", "inflation", "tariff", "sanction", "gdp"),
    "business": ("contract", "order win", "wins order", "partnership",
                 "layoffs", "job cuts", "ceo resigns", "ceo steps down",
                 "buyback", "dividend", "plant", "shutdown"),
    "shock": ("earthquake", "war", "invasion", "attack", "strike", "explosion",
              "hurricane", "flood", "wildfire", "blockade", "outage", "hack",
              "missile", "drone", "coup", "ceasefire", "drought", "famine"),
    # Commodity supply. Missing from the first version, which dropped a
    # Strait of Hormuz story as "no material event" — a chokepoint for a large
    # share of seaborne oil, and the kind of event the event study measured:
    # war in a producing region drives the commodity UP.
    "commodity": ("hormuz", "strait", "chokepoint", "opec", "crude", "oil supply",
                  "pipeline", "refinery", "red sea", "suez", "gas supply",
                  "crop", "harvest", "wheat", "gold price", "copper"),
}

# Themes a professional trades through instruments rather than names. A story
# about Hormuz is traded through oil, not through a ticker in the headline.
THEME_INSTRUMENTS: dict[str, tuple[str, ...]] = {
    "hormuz": ("USO", "XLE"), "strait": ("USO", "XLE"), "opec": ("USO", "XLE"),
    "crude": ("USO", "XLE"), "oil": ("USO", "XLE"), "red sea": ("USO", "XLE"),
    "suez": ("USO", "XLE"), "refinery": ("XLE",), "pipeline": ("XLE",),
    "gas supply": ("UNG",), "gold": ("GLD",), "silver": ("SLV",),
    "wheat": ("WEAT",), "crop": ("DBA",), "copper": ("CPER",),
    "semiconductor": ("SMH",), "chip": ("SMH",), "rate cut": ("TLT",),
    "rate hike": ("TLT",), "bitcoin": ("BTC-USD",), "ethereum": ("ETH-USD",),
}

# Recaps and listicles: they describe what already happened.
RECAP = re.compile(
    r"\b(stocks? to watch|top (gainers|losers)|why .{1,40} (stock|shares) "
    r"(is|are) (up|down|rising|falling|soaring|plunging)|market wrap|"
    r"closing bell|opening bell|morning brief|here'?s what|things to know|"
    r"what to expect|how to (buy|invest)|best stocks|should you buy|"
    r"\d+ stocks|week ahead|in charts|explained|opinion|column|analysis:)",
    re.IGNORECASE)

# A source is demoted to LEARN once it has this many scored checks and its
# hit rate sits this far below chance.
SOURCE_MIN_CHECKS = 30
SOURCE_MARGIN = 0.05


@dataclass(frozen=True)
class Decision:
    verdict: str
    event_class: str | None
    reason: str
    instruments: tuple[str, ...] = ()


def theme_instruments(text: str) -> tuple[str, ...]:
    """Liquid instruments that carry a theme named in the text."""
    low = f" {text.lower()} "
    out: list[str] = []
    for word, symbols in THEME_INSTRUMENTS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            out.extend(s for s in symbols if s not in out)
    return tuple(out)


# USGS titles read "M 6.4 - 45 km SW of Tokyo": no word "earthquake" at all.
_QUAKE = re.compile(r"^\s*M\s?\d+(\.\d+)?\s*-", re.IGNORECASE)


def event_class(text: str) -> str | None:
    if _QUAKE.match(text or ""):
        return "shock"
    low = f" {text.lower()} "
    for cls, words in MATERIAL.items():
        if any(w in low for w in words):
            return cls
    return None


def judge(title: str, summary: str = "", *, tradable: bool,
          source_record: tuple[int, float, float] | None = None) -> Decision:
    """ACT, LEARN or DROP for one item.

    `tradable` says whether it names something liquid enough to trade.
    `source_record` is (checks, hit rate, chance rate) for the item's source,
    when one exists.
    """
    text = f"{title} {summary}"
    if RECAP.search(title or ""):
        return Decision(DROP, None, "a recap of what already happened — in the price")
    cls = event_class(text)
    if cls is None:
        return Decision(DROP, None, "no material event — nothing that moves a price")
    if source_record:
        n, rate, chance = source_record
        if n >= SOURCE_MIN_CHECKS and rate < chance - SOURCE_MARGIN:
            return Decision(LEARN, cls,
                            f"source scored {rate:.0%} against {chance:.0%} chance "
                            f"over {n} checks — kept for study, not traded on")
    via = theme_instruments(text)
    if not tradable and not via:
        return Decision(LEARN, cls, f"a {cls} event with nothing liquid to trade "
                                    "— kept to learn how markets react")
    if not tradable:
        return Decision(ACT, cls, f"a {cls} event, tradable through "
                                  f"{', '.join(via)}", via)
    return Decision(ACT, cls, f"a {cls} event about something tradable", via)


# Capitalised words that are not tickers in a headline, however many
# companies trade under them. "M 6.4 - 45 km SW of Tokyo" matched SW (Smurfit
# WestRock) because SW there means south-west.
_NOT_TICKERS = frozenset({
    "N", "S", "E", "W", "NE", "NW", "SE", "SW", "NNE", "ENE", "ESE", "SSE",
    "SSW", "WSW", "WNW", "NNW", "KM", "MI", "US", "USA", "UK", "EU", "UN",
    "CEO", "CFO", "CTO", "AI", "IPO", "GDP", "CPI", "FDA", "SEC", "ETF",
    "IT", "TV", "PM", "AM", "EV", "OK", "ON", "IN", "AT", "BY", "OR", "AN",
    "Q1", "Q2", "Q3", "Q4", "FY", "YOY", "USD", "INR", "EUR", "GBP", "NATO",
    "OPEC", "RBI", "ECB", "IMF", "WHO", "NYSE", "NSE", "BSE", "LIVE", "NEW",
})


def _ticker_words(title: str) -> set[str]:
    """Upper-case words that could be tickers, filtered the way a trader would.

    Three letters or more count as written, unless they are common
    abbreviations. Two letters count only when marked as tickers — "$SW" or
    "(SW)" — because short capitals are usually directions, units or words.
    """
    text = title or ""
    out = set()
    for w in re.findall(r"\b[A-Z][A-Z0-9.&-]{1,9}\b", text):
        if w in _NOT_TICKERS:
            continue
        if len(w) >= 3:
            out.add(w)
        elif re.search(rf"(\${re.escape(w)}\b|\({re.escape(w)}\))", text):
            out.add(w)
    return out


def matches_tradable(title: str, assets) -> bool:
    """Whether a headline names an asset, by name or by an exact ticker.

    Names match as whole phrases of at least four letters. Tickers match only
    as exact upper-case words in the original headline, so "V" or "BA" does
    not match every sentence containing those letters.
    """
    low = f" {re.sub(r'[^a-z0-9&\' ]', ' ', (title or '').lower())} "
    words = _ticker_words(title)
    for a in assets:
        # The same terms the news matcher uses, so the gate and the matcher
        # can never disagree about what a headline is about.
        terms = a.match_terms() if hasattr(a, "match_terms") else ()
        for term in terms:
            clean = re.sub(r"[^a-z0-9&' ]", " ", term).strip()
            if len(clean) >= 4 and f" {clean} " in low:
                return True
        base = getattr(a, "symbol", "").split("-")[0].split(".")[0]
        if len(base) >= 2 and base in words:
            return True
    return False
