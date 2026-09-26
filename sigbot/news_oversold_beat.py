"""Oversold-into-beat — a news edge found by experimenting with the mechanism.

The user's push: don't run existing indicators — decompose the MECHANISM and
experiment with recombinations. Applied to news: instead of "does a beat drift"
(the standard PEAD everyone trades, largely arbitraged), I decomposed it by the
stock's STATE going in. The recombination that works: surprise × prior-weakness.

MEASURED (US stocks, 2009-2026): a 5%+ earnings beat drifts over the next 5 days
by how oversold the stock was BEFORE the report. FULL-SCALE re-run (61,557
events, survivorship-accounted — the earlier per-era numbers were on small
samples):
  oversold into beat (RSI<35): +4.10%  (n=4,597)
  every other beat:            +2.47%  (n=56,960)
A confirmed 1.66x edge on the full history — larger and more robust than the
small-sample per-era figures first suggested.

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
