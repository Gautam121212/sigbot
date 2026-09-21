"""Indicators sigbot built itself, each tested before it was kept.

CONFIRMED SURPRISE (news). A big earnings beat (+10% or more against
forecasts) whose stock ALSO rose 2%+ beyond the index on the reaction day
kept outperforming over the next 19 trading days: +1.20% / +0.44% / +1.26%
(2016-20 / 2021+ / 2009-15), t 5.2 / 3.0 / 6.0. All big beats together showed
no drift — the cases where the market disagreed with the headline cancelled
it out. It triggers AFTER the reaction day, so a system that learns of news
hours late can still act on it. Misses, and divergent reactions, flip sign
between periods and are not used.
"""
from __future__ import annotations

BIG_SURPRISE = 10.0        # percent against the forecast
CONFIRMING_MOVE = 0.02     # reaction-day return beyond the index
DRIFT_DAYS = 19


def confirmed_surprise(surprise_pct: float | None, reaction_excess: float | None) -> bool:
    """True for a big beat the market confirmed on the day. Missing data never fires."""
    if surprise_pct is None or reaction_excess is None:
        return False
    return surprise_pct >= BIG_SURPRISE and reaction_excess >= CONFIRMING_MOVE
