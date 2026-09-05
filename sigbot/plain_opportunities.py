"""Opportunities in plain words, with colours that mean something checkable.

The digest read like a research memo: source strength 0.49, gap type, ceiling,
enrich(). That is the language the model thinks in, not the language you read
in.

## What the colours mean here, and what they cannot

On the board, green means a measured record clears a bar. **Nothing like that
exists here and nothing can.** IPOs and macro dislocations are single events;
there is no base rate to measure a new one against.

So the colour describes **how complete the case is**, never how likely it is to
work:

    green   the case is complete enough to be worth real time — every heavy
            question already has an answer in the source
    amber   worth reading, but the questions that decide it are unanswered
    grey    cannot get there even if every unknown resolves well

A green card is not a good opportunity. It is a case you can finish evaluating
without guessing. That distinction is the whole reason the wording differs from
the board, and the banner on each card says so.

## Money

`capital_required` is a scored criterion — how much money the thing needs
relative to what a solo operator has — not a figure in rupees. No number is
invented here. The card says "needs little money to start" or "needs real
capital before any revenue", which is what the score actually knows.
"""
from __future__ import annotations

import re

from dataclasses import dataclass

from .venture import PLAN_THRESHOLD, RUBRIC

# What each rubric criterion means to someone deciding whether to spend a
# weekend on it. Written as the question the score is answering.
PLAIN = {
    "demand_evidence": ("Is anyone already paying for this?",
                        "someone already pays for a worse version",
                        "no evidence anyone pays for this yet"),
    "distribution": ("Can you reach a buyer without paying for ads?",
                     "you can reach buyers directly",
                     "no clear way to reach a buyer"),
    "time_to_first_revenue": ("How soon could money come in?",
                              "revenue possible within weeks",
                              "months before anything could be charged"),
    "capital_required": ("How much money to start?",
                         "little money needed to start",
                         "needs real capital before any revenue"),
    "skill_fit": ("Could you actually do the work?",
                  "within reach of what you can do or learn",
                  "needs skills that take a long time to get"),
    "competition_density": ("How crowded is it?",
                            "few people doing this well",
                            "crowded, with established players"),
    "regulatory_friction": ("Will rules get in the way?",
                            "no unusual regulatory hurdle",
                            "licences or approvals stand in the way"),
    "durability": ("Would it last?",
                   "hard for someone to copy quickly",
                   "easy to copy once it works"),
    "evidence_quality": ("How good is the source?",
                         "reported by a source with a record",
                         "weak or single-source reporting"),
}

TYPE_LABEL = {
    "supply_chain_shift": "Supply chain change",
    "regulatory_gap": "Rule change",
    "price_dislocation": "Price dislocation",
    "capacity_shortage": "Capacity shortage",
    "distribution_gap": "Distribution gap",
    "technology_shift": "Technology shift",
    "demographic_shift": "Demographic shift",
    "MACRO": "Macro / economy",
    "IPO": "New listing",
    "COMMODITY": "Commodity",
    "PROPERTY": "Property",
}

GREEN, AMBER, GREY = "#00e676", "#ffd93d", "#8b8b9a"


@dataclass
class PlainCard:
    title: str
    kind: str               # the banner: what sort of thing this is
    colour: str
    verdict: str            # what the colour means, in words
    summary: str            # one paragraph, no jargon
    answered: list[str]     # what the source already settles
    unanswered: list[str]   # what you would have to find out
    money: str
    sources: list[str]

    def render_text(self) -> str:
        """For Telegram. Same shape as the card in the app."""
        lines = [f"{self.kind.upper()} — {self.title}", "", self.verdict, "",
                 self.summary, "", f"Money: {self.money}"]
        if self.answered:
            lines += ["", "Already answered:"] + [f"  · {a}" for a in self.answered[:4]]
        if self.unanswered:
            lines += ["", "You would have to find out:"] + \
                     [f"  · {q}" for q in self.unanswered[:4]]
        if self.sources:
            lines += ["", "From: " + "; ".join(self.sources[:2])]
        return "\n".join(lines)


def _band(score: float, ceiling: float) -> tuple[str, str]:
    """Colour and its meaning. Never about likelihood of success."""
    if score >= PLAN_THRESHOLD:
        return GREEN, ("Complete enough to act on — every heavy question has an "
                       "answer in the source. That is not the same as a good "
                       "idea; it means you can finish judging it without guessing.")
    if ceiling < PLAN_THRESHOLD:
        return GREY, (f"Cannot get there. Even if every unknown resolved in your "
                      f"favour this reaches {ceiling:.0f} out of "
                      f"{PLAN_THRESHOLD:.0f}. Read it as context, not a lead.")
    return AMBER, (f"Worth reading, not yet worth time. It sits at {score:.0f} "
                   f"and could reach {ceiling:.0f} — but only once you answer "
                   "the questions below, which the news cannot.")


def from_candidate(candidate) -> PlainCard:
    """Turn a business candidate into something readable."""
    opp = getattr(candidate, "opportunity", candidate)
    scores = getattr(opp, "scores", {}) or {}
    # Every criterion is always scored — an unscored one raises. What marks an
    # unknown is `needs_enrichment`: the item is held at a neutral 5 because the
    # news cannot speak to it. Treating a missing key as unknown, as an earlier
    # version did, would have found no unknowns at all.
    unknown = set(getattr(candidate, "needs_enrichment", []) or [])
    total = getattr(opp, "total", None)
    if total is None:
        total = sum(scores.get(k, 5) / 10.0 * w for k, (w, *_r) in RUBRIC.items())
    ceiling = getattr(candidate, "ceiling", None)
    if ceiling is None:
        ceiling = total + sum(RUBRIC[k][0] * (1 - scores.get(k, 5) / 10.0)
                              for k in unknown)

    colour, verdict = _band(total, ceiling)
    answered, unanswered = [], []
    for key, (weight, *_r) in sorted(RUBRIC.items(), key=lambda kv: -kv[1][0]):
        question, good, bad = PLAIN.get(key, (key, key, key))
        if key in unknown:
            if weight >= 10:
                unanswered.append(question)
        elif scores.get(key, 5) >= 6:
            answered.append(good)
        elif weight >= 10:
            answered.append(bad)

    if "capital_required" in unknown:
        money = "Not known from the news — you would have to work it out."
    elif scores.get("capital_required", 5) >= 6:
        money = PLAIN["capital_required"][1]
    else:
        money = PLAIN["capital_required"][2]

    return PlainCard(
        title=getattr(opp, "title", "Untitled"),
        kind=TYPE_LABEL.get(getattr(candidate, "gap_type", ""), "Business idea"),
        colour=colour, verdict=verdict,
        summary=getattr(opp, "thesis", "") or "No description in the source.",
        answered=answered, unanswered=unanswered, money=money,
        sources=[str(s) for s in (getattr(opp, "sources", []) or [])])


def _cite(article) -> str:
    """Outlet and date, from an Article or from something already formatted.

    str() on an Article gives its Python repr — the whole object, uid and all,
    printed into the card under "Where it came from". A source line is an
    outlet and a date, not a dataclass dump.
    """
    source = getattr(article, "source", None)
    if source is None:
        return tidy_source(str(article))
    when = getattr(article, "published_at", None)
    cited = f"{source} ({when:%Y-%m-%d})" if when else str(source)
    return tidy_source(cited)


def tidy_source(cited: str) -> str:
    """Repair source lines written before the outlet fix.

    Stored cards from earlier runs carry the raw aggregator query and a
    200-character redirect URL where an outlet name belongs. New cards are
    clean at the source; old ones are cleaned at render, because a store full
    of history should not have to be deleted to fix its display.
    """
    import re

    cited = re.sub(r"https?://\S+", "", cited)
    match = re.search(r"site:([\w.-]+)", cited)
    if match:
        date = re.search(r"\((\d{4}-\d{2}-\d{2})\)", cited)
        return match.group(1) + (f" ({date.group(1)})" if date else "")
    return " ".join(cited.split())


LISTING_WORDS = ("ipo", "listing", "allotment", "gmp", "subscription",
                 "price band", "drhp", "issue opens", "lists on")


def _is_listing_thesis(text: str) -> bool:
    return any(word in text.lower() for word in LISTING_WORDS)


def from_thesis(card) -> PlainCard:
    """Turn an investment or macro thesis into something readable.

    An IPO thesis used to arrive as a copied headline with "look into it"
    attached — no score, no date, no judgement, which is a bookmark rather
    than an idea. Anything that reads like a listing now goes through the same
    ten fixed tests the listing scorer applies, so the card carries a score
    from the coverage, a colour from the score, and the window in the banner.

    The colour still describes how complete the case is, never how likely it
    is to work — the same rule as everywhere else on the page.
    """
    strength = getattr(card, "source_strength", 0.0) or 0.0
    if strength >= 0.75:
        colour, verdict = AMBER, ("Reported by a source with a record, but this "
                                  "model has never been scored against outcomes. "
                                  "Treat it as a thing to look into.")
    else:
        colour, verdict = GREY, (f"Weak sourcing ({strength:.0%}). One outlet, or "
                                 "an outlet without a track record. Read it as a "
                                 "prompt to check elsewhere, nothing more.")

    title_text = getattr(card, "subject", "") or ""
    claim_text = getattr(card, "claim", "") or ""
    full_text = f"{title_text}. {claim_text}"
    kind_label = TYPE_LABEL.get(getattr(card, "category", ""), "Market thesis")

    if _is_listing_thesis(full_text):
        from .listings import score_listing

        scored = score_listing(title_text or "This listing", full_text,
                               sources=[])
        window = scored.window
        # The window leads the banner: "closes 06 Sep" is the single most
        # decision-relevant fact on a listing card, and it was nowhere.
        state = window.state if window else "unknown"
        kind_label = {"open": "IPO — open now",
                      "last day": "IPO — LAST DAY",
                      "upcoming": "IPO — upcoming",
                      "closed": "IPO — closed",
                      "unknown": "IPO — dates unknown"}[state]
        colour, verdict = scored.colour, scored.verdict
        return PlainCard(
            title=title_text or "Untitled",
            kind=kind_label, colour=colour, verdict=verdict,
            # The verdict already carries the window note for non-actionable
            # cards; repeating it in the summary printed the same sentence
            # twice back to back.
            summary=((window.note + " ") if window and window.actionable
                     else "") + claim_text,
            answered=[r.question for r in scored.results
                      if r.observed and r.favourable][:5],
            unanswered=[r.question for r in scored.results
                        if not r.observed][:5],
            money=f"{scored.scored} of a possible {scored.possible} points on "
                  "the ten tests the coverage could answer.",
            sources=[_cite(a) for a in (getattr(card, "articles", []) or [])])

    return PlainCard(
        title=getattr(card, "subject", "Untitled"),
        kind=TYPE_LABEL.get(getattr(card, "category", ""), "Market thesis"),
        colour=colour, verdict=verdict,
        summary=getattr(card, "claim", "") or "No claim stated.",
        answered=[],
        unanswered=[str(x) for x in (getattr(card, "must_be_true", []) or [])],
        money="Not stated. A market thesis says nothing about what acting on it "
              "would cost you.",
        # str() on an Article gives its Python repr — the whole object, uid
        # and all, printed into the card under "Where it came from". A source
        # line is an outlet and a date, not a dataclass dump.
        sources=[_cite(a) for a in (getattr(card, "articles", []) or [])])


# How long a card of each kind stays useful. Time-sensitive events go stale
# fast: an allotment story is worthless the day after allotment, whatever it
# said. A supply-chain thesis is still readable a month on.
#
# Age is the reliable signal, not parsed dates. "Deepa Jewellers IPO allotment
# likely today" contains no date at all, so window parsing kept it — but "today"
# in a story published four days ago is exactly the evidence needed, and the
# card never carried the publication date.
SHELF_LIFE_DAYS = {
    "allotment": 2, "gmp": 2, "listing gain": 2, "subscription": 4,
    "ipo": 7, "closes": 3, "opens": 10, "price band": 7,
}
DEFAULT_SHELF_LIFE = 30


def shelf_life(text: str) -> int:
    """Days this kind of item stays worth reading."""
    lowered = text.lower()
    lives = [days for word, days in SHELF_LIFE_DAYS.items() if word in lowered]
    return min(lives) if lives else DEFAULT_SHELF_LIFE


def stale(card, today=None) -> bool:
    """Whether the coverage behind this card is too old to act on.

    A card with no date at all is kept — this only fires when a published_at
    is available and the shelf life has passed.
    """
    from datetime import datetime, timezone

    published = getattr(card, "published_at", None)
    if published is None:
        for source in (getattr(card, "sources", None) or []):
            match = re.search(r"\((\d{4}-\d{2}-\d{2})\)", str(source))
            if match:
                published = datetime.fromisoformat(match.group(1)).replace(
                    tzinfo=timezone.utc)
                break
    if published is None:
        return False

    now = today or datetime.now(timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    text = " ".join(str(x) for x in (getattr(card, "title", ""),
                                     getattr(card, "summary", "")))
    return (now - published).days > shelf_life(text)


def _newest_source_date(card):
    """The most recent publication date found in the card's source lines."""
    import re
    from datetime import date

    newest = None
    for source in (getattr(card, "sources", None) or []):
        match = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", str(source))
        if match:
            seen = date(*map(int, match.groups()))
            newest = seen if newest is None or seen > newest else newest
    return newest


def expired(card) -> bool:
    """Whether this card describes something that has already happened.

    Two paths produce IPO cards: the listing scorer, which reads dates, and the
    venture thesis path, which does not. So "Deepa Jewellers IPO allotment
    likely today" arrived with no timing at all and sat in Ideas after the
    issue closed — an opportunity you could not take, described as one you
    could.

    Only clearly-past items are dropped. A card with no date is kept, because
    absence of a date is not evidence that it is over, and silently discarding
    it would hide things that are still live.
    """
    import re
    from datetime import date, datetime, timezone

    from .listings import read_window

    text = " ".join(str(x) for x in (
        getattr(card, "title", ""), getattr(card, "summary", ""),
        getattr(card, "verdict", "")))
    # Anchor relative words to the article's publication date where we have
    # one — "today" in an old article is that day, not this one.
    published = _newest_source_date(card)
    window = read_window(text, today=published)
    if window.state == "closed":
        return True

    # An IPO card with no readable dates cannot be verified live, and a
    # listing window is days wide — so after two days the odds it is still
    # open are poor and the card is noise either way. Undated non-listing
    # theses (a war moving wheat, a policy shift) have no such clock and are
    # kept; the age rule is only for things that expire by construction.
    if window.state == "unknown" and _is_listing_thesis(text):
        # One paid-nothing web lookup before giving up on the dates. Gated on
        # env keys; absent keys, behaviour is unchanged.
        from .listings import lookup_window

        found = lookup_window(getattr(card, "title", "") or text[:60])
        if found is not None:
            return found.state == "closed"
        newest: date | None = None
        for source in (getattr(card, "sources", None) or []):
            match = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", str(source))
            if match:
                # Not 'found' — that name already holds the looked-up Window
                # above, and shadowing it with a date is exactly the kind of
                # reuse that reads fine and types wrong.
                seen = date(*map(int, match.groups()))
                newest = seen if newest is None or seen > newest else newest
        if newest and (datetime.now(timezone.utc).date() - newest).days > 2:
            return True
    return False or stale(card)


def render_plain(cards, candidates) -> str:
    """The whole scan in plain words, for Telegram."""
    plain = [from_thesis(c) for c in cards] + [from_candidate(c) for c in candidates]
    if not plain:
        return ""
    order = {GREEN: 0, AMBER: 1, GREY: 2}
    plain.sort(key=lambda p: order.get(p.colour, 3))

    # Six cards, strongest case first. Sending every match turned a busy news
    # day into forty-two notifications; a digest nobody reads is worse than a
    # short one, and the rest are on the Ideas tab where they can be browsed
    # rather than pushed.
    shown = plain[:6]
    out = [f"{len(plain)} thing(s) worth a look"
           + (f" — showing the {len(shown)} with the most complete case; "
              "the rest are on the Ideas tab." if len(plain) > len(shown)
              else ""), ""]
    out += ["\n" + p.render_text() for p in shown]
    out += ["", "Colours describe how complete the case is, not how likely it "
                "is to work. Nothing here has been checked against what actually "
                "happened, and single events never can be — each one happens once."]
    return "\n".join(out)
