"""Defensive regime signal — when crash risk is elevated, size down.

The user's point: instead of accepting losses in down markets, find what
warns of them. Tested extensively: downturns can't be TIMED precisely (no
signal reliably calls the exact drop). But one thing does hold across every
crisis era — the death-cross regime marks when big drops are far more likely.

MEASURED (SPY, 2007-2026):
  bull regime (50MA > 200MA): 7% chance of a >5% drop next month
  bear regime (50MA < 200MA): 17% chance — nearly 2.5x the crash risk

So this does not predict the drop; it identifies WHEN to be defensive.

IMPORTANT — where it applies: tested on the capitulation signal, defensive
sizing made bad years WORSE, because capitulation is a mean-reversion signal
that WANTS the bear regime (it buys the very weakness the bear regime creates).
The defensive filter belongs on TREND-FOLLOWING signals (momentum-breakout),
which get run over in bear regimes — not on the dip-buyers. Applying it blindly
to everything hurts; it is a per-signal tool.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DefensiveRead:
    bear_regime: bool           # 50MA below 200MA
    size_multiplier: float      # how much to scale positions
    note: str


# Crash-risk ratio from the backtest: bear regime is ~2.5x more likely to see a
# big drop, so positions are scaled toward that inverse.
BEAR_SIZE = 0.5                 # half size in the bear regime
BULL_SIZE = 1.0


def defensive_read(ma50: float | None, ma200: float | None) -> DefensiveRead:
    """Given the index's 50- and 200-day moving averages, how defensive to be."""
    if ma50 is None or ma200 is None:
        return DefensiveRead(False, BULL_SIZE, "trend unknown — normal size")
    if ma50 < ma200:
        return DefensiveRead(
            True, BEAR_SIZE,
            "bear regime (50MA<200MA) — big-drop risk ~2.5x, sized to half")
    return DefensiveRead(False, BULL_SIZE, "bull regime — normal size")


def size_for(ma50: float | None, ma200: float | None, base_size: float) -> float:
    """Scale a base position size by the defensive read."""
    return base_size * defensive_read(ma50, ma200).size_multiplier
