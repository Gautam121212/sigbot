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


def from_thesis(card) -> PlainCard:
    """Turn an investment or macro thesis into something readable."""
    strength = getattr(card, "source_strength", 0.0) or 0.0
    if strength >= 0.75:
        colour, verdict = AMBER, ("Reported by a source with a record, but this "
                                  "model has never been scored against outcomes. "
                                  "Treat it as a thing to look into.")
    else:
        colour, verdict = GREY, (f"Weak sourcing ({strength:.0%}). One outlet, or "
                                 "an outlet without a track record. Read it as a "
                                 "prompt to check elsewhere, nothing more.")

    return PlainCard(
        title=getattr(card, "subject", "Untitled"),
        kind=TYPE_LABEL.get(getattr(card, "category", ""), "Market thesis"),
        colour=colour, verdict=verdict,
        summary=getattr(card, "claim", "") or "No claim stated.",
        answered=[],
        unanswered=[str(x) for x in (getattr(card, "must_be_true", []) or [])],
        money="Not stated. A market thesis says nothing about what acting on it "
              "would cost you.",
        sources=[str(a) for a in (getattr(card, "articles", []) or [])])


def render_plain(cards, candidates) -> str:
    """The whole scan in plain words, for Telegram."""
    plain = [from_thesis(c) for c in cards] + [from_candidate(c) for c in candidates]
    if not plain:
        return ""
    order = {GREEN: 0, AMBER: 1, GREY: 2}
    plain.sort(key=lambda p: order.get(p.colour, 3))

    out = [f"{len(plain)} thing(s) worth a look", ""]
    out += ["\n" + p.render_text() for p in plain]
    out += ["", "Colours describe how complete the case is, not how likely it "
                "is to work. Nothing here has been checked against what actually "
                "happened, and single events never can be — each one happens once."]
    return "\n".join(out)
