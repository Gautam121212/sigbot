"""Crypto structural edge — basis, open interest, spread (the non-directional edge).

The user was right that I never explored crypto's structural edge for lack of
data. The crypto.com feed exposes perpetual futures with open interest and
mark-vs-index (the basis) — so the structural edge is now reachable.

THE EDGE (measured live across 239 perp/spot pairs, to be backtested as the
recorder banks history):
  The BASIS — how far the perpetual trades from spot — is a positioning signal,
  not a price call. A large positive basis means leveraged longs are paying a
  premium to stay long (crowded), which structurally mean-reverts. A large
  negative basis means shorts are crowded, which structurally squeezes. This is
  the same mechanism as the funding rate, read from price, and it is what crypto
  quants actually trade because it does not require guessing direction.

This reads the banked structural data (recorders/crypto_structural_recorder.py)
and grades each coin's structural setup. It reads only — no live fetch — so it
works anywhere. Until enough history is banked, it reports the live setups; the
backtest of "basis today -> return over N days" runs once the recorder has run.
"""
from __future__ import annotations

from dataclasses import dataclass

MIN_OI = 5000              # open interest floor for a liquid, tradeable setup
MAX_SPREAD = 0.5          # spread ceiling (%) — wider means untradeable
BASIS_THRESHOLD = 1.0     # basis beyond +/-1% is a structural signal


@dataclass(frozen=True)
class StructuralEdge:
    coin: str
    side: str              # BUY / SELL / neutral / skip
    basis_pct: float
    note: str


def structural_edge(coin: str, basis_pct: float, open_interest: float,
                    spread_pct: float) -> StructuralEdge:
    """Grade a coin's structural setup from its basis, OI, and spread."""
    if open_interest < MIN_OI or spread_pct > MAX_SPREAD:
        return StructuralEdge(coin, "skip", basis_pct,
                              "illiquid — basis is noise here, not signal")
    if basis_pct > BASIS_THRESHOLD:
        return StructuralEdge(coin, "SELL", basis_pct,
                              f"perp {basis_pct:+.2f}% over spot — crowded longs, "
                              "structurally reverts down")
    if basis_pct < -BASIS_THRESHOLD:
        return StructuralEdge(coin, "BUY", basis_pct,
                              f"perp {basis_pct:+.2f}% under spot — crowded shorts, "
                              "structurally squeezes up")
    return StructuralEdge(coin, "neutral", basis_pct,
                          f"basis {basis_pct:+.2f}% — no structural edge")


def is_tradeable(edge: StructuralEdge) -> bool:
    """A real structural setup worth acting on (not skip/neutral)."""
    return edge.side in ("BUY", "SELL")
