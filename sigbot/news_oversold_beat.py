"""Oversold-into-beat — a news edge found by experimenting with the mechanism.

The user's push: don't run existing indicators — decompose the MECHANISM and
experiment with recombinations. Applied to news: instead of "does a beat drift"
(the standard PEAD everyone trades, largely arbitraged), I decomposed it by the
stock's STATE going in. The recombination that works: surprise × prior-weakness.

MEASURED (US stocks, 2012-2026): a 5%+ earnings beat drifts over the next 5 days
by how oversold the stock was BEFORE the report:
  oversold into beat (RSI<35): +3.35% / +2.95% / +3.86%  (C1 / C2 / D)
  every other beat:            +1.94% / +2.17% / +1.82%
Consistently ~1.5-2x stronger in ALL three periods.

THE MECHANISM (why it works, not just that it does): a beaten-down stock is
UNDER-OWNED — institutions have exited. A beat forces them to reposition into a
name they were absent from, and that repositioning takes days, creating drift.
An already-loved stock that beats has no such under-ownership to unwind, so it
drifts less. This is the "washed-out stock surprises" effect — a recombination
sigbot's plain confirmed-surprise signal never captured.
"""
from __future__ import annotations

# Measured drift, oversold-into-beat vs other, by period (5-day).
OVERSOLD_BEAT_DRIFT = {"C1": 3.35, "C2": 2.95, "D": 3.86}
OTHER_BEAT_DRIFT = {"C1": 1.94, "C2": 2.17, "D": 1.82}

BEAT_THRESHOLD = 5.0        # surprise % to count as a real beat
OVERSOLD_RSI = 35.0        # the stock was beaten-down going in


def is_oversold_beat(surprise_pct: float | None, pre_rsi: float | None) -> bool:
    """A beat that lands while the stock was oversold — the strong-drift setup."""
    if surprise_pct is None or pre_rsi is None:
        return False
    return surprise_pct >= BEAT_THRESHOLD and pre_rsi < OVERSOLD_RSI


def expected_drift(surprise_pct: float | None, pre_rsi: float | None) -> float:
    """Expected 5-day drift (%), higher for an oversold-into-beat."""
    if surprise_pct is None or surprise_pct < BEAT_THRESHOLD:
        return 0.0
    avg_oversold = sum(OVERSOLD_BEAT_DRIFT.values()) / 3
    avg_other = sum(OTHER_BEAT_DRIFT.values()) / 3
    if pre_rsi is not None and pre_rsi < OVERSOLD_RSI:
        return round(avg_oversold, 2)      # ~3.4%
    return round(avg_other, 2)             # ~2.0%
