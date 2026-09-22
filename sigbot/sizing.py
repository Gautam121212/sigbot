"""Fractional-Kelly sizing — the profitable gate that lets risk through safely.

THE PROBLEM THIS SOLVES
-----------------------
The models had a binary gate: proven edge -> trade, else -> reject. That
rejects every survivable-but-unproven bet, which was the complaint. Real
desks do not gate binary. They SIZE: a positive-edge bet gets a position
scaled to its edge; a negative-edge bet gets zero. Risk is admitted in
proportion to how much it pays, and capped so no bet can cause ruin.

THE METHOD, AND WHY THIS FORM
-----------------------------
The Kelly criterion gives the growth-optimal fraction of capital to risk from
an edge: f = (b*p - q) / b, where p is win probability, q = 1-p, and b is the
win/loss payoff ratio. Full Kelly is famously too volatile because p and b are
estimates, and a 5-point error in p can treble the bet. So every professional
source uses FRACTIONAL Kelly — a quarter to a half — with a hard 2% cap:

  * quarter-to-half Kelly keeps ~75-90% of the growth at a fraction of the
    drawdown (MacLean-Ziemba; CFA 2% rule);
  * the cap means one bet, or a cluster, can never take the account down;
  * negative edge returns zero — the fix for a bad edge is not to trade it,
    never to sytematically size it down and keep going.

This is the SAME barbell logic as ventures.py, expressed for repeated trades:
admit risk, size it to its edge, cap it at survivable. It changes only SIZE,
never whether a model is judged to have an edge (that stays with the learning
loop, strict as ever).
"""
from __future__ import annotations

from dataclasses import dataclass

KELLY_FRACTION = 0.25       # quarter-Kelly: the conservative professional default
MAX_RISK_FRACTION = 0.02    # CFA 2% rule — the hard ceiling, whatever Kelly says
MIN_RISK_FRACTION = 0.0025  # below this a bet is too small to bother taking


def kelly_fraction(p_win: float, payoff_ratio: float) -> float:
    """Full Kelly fraction of capital to risk. Negative means no bet."""
    if payoff_ratio <= 0:
        return 0.0
    q = 1.0 - p_win
    return (payoff_ratio * p_win - q) / payoff_ratio


@dataclass(frozen=True)
class Sizing:
    risk_fraction: float      # of capital, after fraction + cap
    full_kelly: float
    reason: str
    take: bool


def size(p_win: float, payoff_ratio: float,
         kelly_frac: float = KELLY_FRACTION,
         cap: float = MAX_RISK_FRACTION) -> Sizing:
    """How much of capital to risk on a bet with this edge.

    Returns a small, capped fraction for a positive-edge bet — however
    uncertain — and zero for a negative-edge one. This is the gate: not
    yes/no, but how-much, with zero as the natural "no".
    """
    full = kelly_fraction(p_win, payoff_ratio)
    if full <= 0:
        return Sizing(0.0, round(full, 4), "negative edge — no bet, at any size", False)
    risk = min(full * kelly_frac, cap)
    if risk < MIN_RISK_FRACTION:
        return Sizing(0.0, round(full, 4),
                      f"edge too thin ({full:.1%} full Kelly) — not worth the slot", False)
    capped = " (capped)" if full * kelly_frac > cap else ""
    return Sizing(round(risk, 4), round(full, 4),
                  f"{kelly_frac:.0%} Kelly on a {full:.1%} edge{capped}", True)


def size_from_record(wins: int, losses: int, avg_win: float, avg_loss: float,
                     **kw) -> Sizing:
    """Sizing straight from a live track record — the form a model feeds it.

    A negative or empty record returns no bet. avg_loss is given as a positive
    number (the size of a typical loss).
    """
    n = wins + losses
    if n < 20 or avg_loss <= 0:
        return Sizing(0.0, 0.0, f"only {n} closed bets — too few to size", False)
    p = wins / n
    payoff = avg_win / avg_loss
    return size(p, payoff, **kw)
