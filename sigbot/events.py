"""Event studies: how assets actually moved when a kind of event happened.

WHY THIS EXISTS
---------------
An experienced trader carries a memory of what happened last time: when war
broke out in a commodity-producing region, what did gold do, what did oil do,
what did equities do, and for how long. That memory is what lets them act in
minutes rather than reasoning from scratch while the price moves.

The danger is the other kind of memory — a confident narrative. "War, so
commodities fall" is a sentence that sounds like analysis and has the
direction wrong. Reasoning from a story in real time is exactly how that
error gets made, and it gets made under the most pressure at the moment it
matters most.

So this module stores REACTIONS, not reasoning. Each entry records what a
class of event actually did to each asset, over which window, with the source.
When a new event of that class occurs, the model starts from the measured
record — the direction, the size, the duration — and only then asks whether
this time differs.

WHAT THE FIRST ENTRY TEACHES
----------------------------
Russia's invasion of Ukraine, 24 February 2022. Everything commodity-linked
ROSE, and sharply:

    gold       +3.4% on the day, to $1,971 — highest since September 2020
    silver     +4.2% on the day, to $25.56
    palladium  +7% on the day (Russia supplies ~40% of world output)
    Brent oil  +8% on the day, through $100; +18% monthly average Feb->Mar
    wheat      +29% in March, among the largest monthly rises in a century
    equities   European indices down close to 5% on the day

And the detail that makes it a trading fact rather than a headline: gold had
also FALLEN on 15 February, on reports of Russian de-escalation. The market
was pricing the probability of war, in both directions, for a week before the
invasion. By the morning of the 24th, a large part of the move was already in.

Sources: Kansas City Fed, "Turmoil in Commodity Markets Following Russia's
Invasion of Ukraine"; St Louis Fed, "Russia's Invasion of Ukraine and Its
Impact on Stock Prices" (June 2022); Reuters and S&P Global Platts reporting
of 24 February 2022.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Reaction:
    """What one asset did in response to one event."""

    asset: str
    direction: str          # "UP" or "DOWN"
    move_pct: float         # signed, over `window`
    window: str             # "day", "month", ...
    why: str                # the mechanism, stated plainly


@dataclass(frozen=True)
class EventStudy:
    """A class of event and the measured reactions to one instance of it."""

    event_class: str        # the reusable category, e.g. "war-in-commodity-region"
    instance: str           # the specific occurrence
    date: str
    reactions: tuple[Reaction, ...]
    priced_in_early: bool   # was the move largely made BEFORE the event itself?
    lesson: str             # the tradeable fact, in one sentence
    sources: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        lines = [f"{self.instance} ({self.date}) — {self.event_class}"]
        for r in self.reactions:
            arrow = "rose" if r.direction == "UP" else "fell"
            lines.append(f"  {r.asset:<10} {arrow} {abs(r.move_pct):.1f}% "
                         f"({r.window}) — {r.why}")
        if self.priced_in_early:
            lines.append("  Much of the move was made BEFORE the event: the "
                         "market was pricing its probability in both "
                         "directions for days beforehand.")
        lines.append(f"  Lesson: {self.lesson}")
        return "\n".join(lines)


STUDIES: tuple[EventStudy, ...] = (
    EventStudy(
        event_class="war-in-commodity-region",
        instance="Russia invades Ukraine",
        date="2022-02-24",
        reactions=(
            Reaction("gold", "UP", 3.4, "day",
                     "safe-haven buying as risk appetite collapsed"),
            Reaction("silver", "UP", 4.2, "day",
                     "follows gold, plus supply risk to industrial metals"),
            Reaction("palladium", "UP", 7.0, "day",
                     "Russia supplies roughly 40% of world output"),
            Reaction("oil", "UP", 8.0, "day",
                     "Russia supplies about 10% of world oil"),
            Reaction("oil", "UP", 18.0, "month",
                     "sanctions and disrupted supply through March"),
            Reaction("wheat", "UP", 29.0, "month",
                     "Russia and Ukraine together export 29% of world wheat"),
            Reaction("equities", "DOWN", 5.0, "day",
                     "European indices; capital moved into safe havens"),
        ),
        priced_in_early=True,
        lesson=("War in a region that produces a commodity drives that "
                "commodity UP, not down, because it cuts supply — and it "
                "drives gold up as a safe haven. Much of the move happens "
                "on the approach, so being first to the headline is too late."),
        sources=(
            "Kansas City Fed — Turmoil in Commodity Markets Following "
            "Russia's Invasion of Ukraine",
            "St Louis Fed — Russia's Invasion of Ukraine and Its Impact on "
            "Stock Prices (June 2022)",
            "Reuters / S&P Global Platts, 24 February 2022",
        ),
    ),
)


def lookup(event_class: str) -> list[EventStudy]:
    """Every recorded instance of a class of event."""
    return [s for s in STUDIES if s.event_class == event_class]


def expected_direction(event_class: str, asset: str) -> str | None:
    """The historical direction for this asset in this kind of event, if known.

    Returns None rather than a guess when there is no record, or when the
    record disagrees with itself. One instance is not a rule, and a model
    that treats it as one is back to reasoning from a story — just a story
    with a date attached.
    """
    moves = [r.direction for s in lookup(event_class)
             for r in s.reactions if r.asset == asset]
    if not moves:
        return None
    if len(set(moves)) > 1:
        return None
    return moves[0]


def instances(event_class: str) -> int:
    """How many independent occurrences back this class. One is an anecdote."""
    return len({s.instance for s in lookup(event_class)})


def describe(studies: Sequence[EventStudy] = STUDIES) -> str:
    lines = ["Event studies — how assets actually reacted", ""]
    for s in studies:
        lines.append(s.summary())
        lines.append("")
    lines.append("  Each class currently rests on ONE instance. That is a "
                 "starting point, not a rule: a second war, a second rate "
                 "shock, a second pandemic will either confirm the pattern "
                 "or show it was specific to that occasion. Until then the "
                 "model treats these as the prior to beat, not the answer.")
    return "\n".join(lines)
