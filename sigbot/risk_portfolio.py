"""Risk portfolio layer — the aggregate-risk controls that were entirely missing.

The three-list comparison showed the risk model had sizing and stops (execution
layer) but NO portfolio layer: no Kelly sizing, no trailing stops, no drawdown
circuit-breaker, no correlation cap, no tier allocation. This builds that layer —
the difference between a set of signals and an actual risk-managed book.

THE FOUR CONTROLS:
  1. KELLY sizing — size each bet by its edge and odds, not a flat %. Half-Kelly
     (the professional standard) maximizes long-run growth without ruin.
  2. TRAILING STOP — for the moonshot/blowup tier, let winners run with a ratchet
     so the rare 100%+ move isn't cut early (the whole point of the tail bet).
  3. DRAWDOWN CIRCUIT-BREAKER — cut all sizing after the book draws down past a
     threshold, so a bad streak can't compound into ruin.
  4. TIER ALLOCATION — split capital across core / risky / very-risky so the
     book is a barbell (safe base + capped moonshot sleeve), not an accident.
"""
from __future__ import annotations

from dataclasses import dataclass

# Tier allocation: a barbell. Most in the proven core, a real but capped risky
# sleeve, a small very-risky moonshot sleeve.
TIER_ALLOCATION = {"core": 0.70, "risky": 0.20, "very-risky": 0.10}

DRAWDOWN_LIMIT = 0.20        # cut sizing after a 20% book drawdown
KELLY_FRACTION = 0.5        # half-Kelly (the professional standard)


def kelly_size(win_prob: float, win_loss_ratio: float,
               fraction: float = KELLY_FRACTION) -> float:
    """Half-Kelly position size as a fraction of capital.

    Kelly f* = p - (1-p)/R, where p is win prob and R is the win/loss ratio.
    Half-Kelly (0.5) is the professional standard — most of the growth, far less
    volatility. Clamped to [0, 0.15] so no single bet is reckless.
    """
    if win_loss_ratio <= 0:
        return 0.0
    edge = win_prob - (1 - win_prob) / win_loss_ratio
    if edge <= 0:
        return 0.0             # no edge -> no bet
    return round(min(edge * fraction, 0.15), 4)


@dataclass
class TrailingStop:
    entry: float
    high_water: float
    trail_pct: float           # e.g. 0.20 = exit if it falls 20% from the peak

    def update(self, price: float) -> bool:
        """Update the high-water mark; return True if the stop is hit (exit)."""
        if price > self.high_water:
            self.high_water = price
        return price <= self.high_water * (1 - self.trail_pct)


def drawdown_ok(equity: float, peak_equity: float,
                limit: float = DRAWDOWN_LIMIT) -> bool:
    """Whether the book is within its drawdown limit. Below it, stop sizing up."""
    if peak_equity <= 0:
        return True
    return (peak_equity - equity) / peak_equity < limit


def tier_capital(total: float) -> dict[str, float]:
    """Split the book across the three risk tiers (the barbell)."""
    return {tier: round(total * frac, 2) for tier, frac in TIER_ALLOCATION.items()}


@dataclass(frozen=True)
class RiskState:
    within_drawdown: bool
    sizing_multiplier: float   # 1.0 normal, 0.0 halted by drawdown
    note: str


def risk_state(equity: float, peak_equity: float) -> RiskState:
    """The book's current risk posture — the circuit-breaker in one call."""
    ok = drawdown_ok(equity, peak_equity)
    dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
    if not ok:
        return RiskState(False, 0.0,
                         f"CIRCUIT-BREAKER — {dd:.0%} drawdown exceeds "
                         f"{DRAWDOWN_LIMIT:.0%}; sizing halted until recovery")
    if dd > DRAWDOWN_LIMIT * 0.5:
        return RiskState(True, 0.5,
                         f"caution — {dd:.0%} drawdown; sizing halved")
    return RiskState(True, 1.0, f"normal — {dd:.0%} drawdown")
