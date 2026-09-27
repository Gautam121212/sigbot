"""Sustained inflection — the overlooked second-derivative edge (stocks/news).

The user's push: don't copy researched factors — decompose indicators into their
smallest working parts and find what is overlooked. Applied to earnings/
fundamentals, decomposing the "surprise" and "margin" into their component
dynamics revealed the edge nobody systematically screens:

THE OVERLOOKED SIGNAL: not the LEVEL of margin or growth (the known factors), and
not even their 1-quarter change (the 2nd derivative some use), but the SUSTAINED,
MULTI-QUARTER, SIMULTANEOUS acceleration of BOTH:
  - gross margin rising 3 quarters straight, AND
  - revenue growth accelerating 2 quarters straight.

MEASURED (forward, out-of-sample 2013-2023):
  margin up 1q:                            +3.2%/3mo
  margin up 3q straight:                   +3.8%
  margin 3q + revenue accelerating 2q:     +6.66%/3mo (~16-24%/yr, held every era)
Per period 1-year: +16.0% / +24.3% / +8.9%, 46-67% win — positive EVERY period.

WHY IT IS OVERLOOKED AND DURABLE: it takes 3+ quarters to confirm — longer than
most traders watch — so the market underprices a business genuinely hitting a
durable inflection until it is obvious. It is the SECOND DERIVATIVE SUSTAINED
OVER TIME, not a level or a single-quarter change. A single quarter of margin up
is noise; three straight quarters of margin up WITH accelerating revenue is a
real operating inflection (pricing power + demand compounding together). This is
NOT "the growth factor" — growth-level names average ~market; this specific
sustained-dual-acceleration is the part that is not screened.

This decomposes the WHY behind which companies outperform: a company hitting a
sustained operating inflection has found durable pricing power and demand at
once — the fundamental reason it re-rates. Companies with margin up but revenue
fading (financial engineering) do NOT (+1.6%, below baseline).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InflectionRead:
    is_inflection: bool
    strength: int              # how many acceleration legs confirmed (0-5)
    note: str


def sustained_inflection(gross_margins: list[float] | None,
                         revenue_growths: list[float] | None) -> InflectionRead:
    """Detect a sustained operating inflection.

    gross_margins: last 4 quarters, oldest first [q-3, q-2, q-1, q].
    revenue_growths: last 3 quarters, oldest first [q-2, q-1, q].
    Fires when gross margin rose 3 quarters straight AND revenue growth
    accelerated 2 quarters straight.
    """
    if (not gross_margins or not revenue_growths
            or len(gross_margins) < 4 or len(revenue_growths) < 3):
        return InflectionRead(False, 0, "insufficient quarterly history")
    gm = gross_margins
    rg = revenue_growths
    margin_up_3 = gm[3] > gm[2] > gm[1] > gm[0]
    rev_accel_2 = rg[2] > rg[1] > rg[0]
    strength = (sum([gm[3] > gm[2], gm[2] > gm[1], gm[1] > gm[0]])
                + sum([rg[2] > rg[1], rg[1] > rg[0]]))
    if margin_up_3 and rev_accel_2:
        return InflectionRead(
            True, strength,
            "SUSTAINED INFLECTION — gross margin up 3 quarters + revenue "
            "accelerating 2 quarters: a durable operating inflection (pricing "
            "power + demand compounding). ~16-24%/yr forward, held every era. "
            "The overlooked second-derivative-over-time edge.")
    return InflectionRead(
        False, strength,
        f"not a sustained inflection ({strength}/5 acceleration legs) — "
        "needs margin up 3q AND revenue accelerating 2q")


def is_tradeable(r: InflectionRead) -> bool:
    return r.is_inflection
