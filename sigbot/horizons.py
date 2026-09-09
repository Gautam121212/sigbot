"""What kind of claim is this, over what window, and what would kill it?

A signal without a horizon is unreadable: "AAPL up" means something entirely
different over three hours than over three months, and a reader who guesses
wrong will judge a correct call as a failure or hold a wrong one far too long.
So every model states its window, in its own words, on every card.

The falsifier matters more. A claim that cannot be wrong is not a claim, and
the fastest way to spot an unfalsifiable one is to try writing the sentence
that would refute it. Each entry below carries that sentence. Where a model
cannot have one — a single unrepeatable event — the entry says so plainly
rather than inventing a test that could never be run.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Horizon:
    badge: str          # short label a reader can scan
    window: str         # how long the claim is about
    colour: str         # CSS variable, matching the site's restrained palette
    falsifier: str      # the sentence that would prove this wrong


# Ordered shortest window first, because that is how a reader triages: what
# needs a decision today sits above what needs one this quarter.
HORIZONS: dict[str, Horizon] = {
    "crypto15m": Horizon(
        badge="Trade",
        window="next 3 hours",
        colour="var(--green)",
        falsifier="The pair does not move the way this says within three "
                  "hours, or moves less than the round-trip cost."),
    "news": Horizon(
        badge="Trade",
        window="next 24 hours",
        colour="var(--green)",
        falsifier="The named asset does not move in the stated direction by "
                  "the next close, or the story turns out to be already "
                  "priced in."),
    "daily": Horizon(
        badge="Trade",
        window="next session",
        colour="var(--green)",
        falsifier="The stock closes the next session on the other side of "
                  "where this pointed."),
    "contagion": Horizon(
        badge="Watch",
        window="1 to 5 sessions",
        colour="var(--amber)",
        falsifier="The follower does not react within five sessions, or "
                  "reacts in the opposite direction to the leader."),
    "opportunity": Horizon(
        badge="Thesis",
        window="weeks to months",
        colour="var(--indigo)",
        falsifier="Nothing here can be scored. A single event happens once, "
                  "so there is no repeat to be right or wrong about — which "
                  "is exactly why it is never called a signal."),
    "paper": Horizon(
        badge="Measurement",
        window="whole record to date",
        colour="var(--teal)",
        falsifier="This is not a claim about the future at all. It reports "
                  "what already-scored predictions would have paid after "
                  "costs, and it is wrong only if the arithmetic is wrong."),
}

_UNKNOWN = Horizon(
    badge="Unclassified",
    window="window not stated",
    colour="var(--faint)",
    falsifier="This model has not declared its window or its falsifier. "
              "Until it does, treat nothing here as actionable.")


def horizon_for(model_id: str) -> Horizon:
    """The window and falsifier for a model.

    An unknown model gets an entry that says it is unclassified rather than a
    plausible default. A wrong horizon is worse than a missing one: it tells
    the reader to act on a timescale nobody verified.
    """
    return HORIZONS.get(model_id, _UNKNOWN)
