"""Crypto move-detection engine — volume/news patterns that precede big moves.

The user's new angle: stop testing price direction (no edge) and instead scan
volume, bars, and news to detect when a move is COMING — analyse the patterns
and reasons behind moves, don't just constantly poll. Same reverse-engineering
method used for the other models: find the actual big moves, then look at what
preceded them.

THE SIGNALS (the precursors of a big crypto move, to be confirmed as the
recorder banks history):
  1. VOLUME SPIKE — an hourly volume far above its recent average is the market
     acting on information before the full move plays out. The single best
     early-warning in liquid crypto (structural: volume = conviction/urgency).
  2. VOLATILITY EXPANSION — the hourly range widening after a quiet stretch:
     the coiled-then-releasing pattern that precedes trending moves.
  3. NEWS-ATTENTION SURGE — a jump in crypto news volume (from the banked
     attention feed) that leads price, because coverage front-runs the crowd.
  4. BASIS SHIFT — the perp/spot basis moving fast (from the structural feed):
     leverage repositioning ahead of a move.

This engine READS banked hourly data and flags when these precursors stack — it
does not poll live. The more precursors align, the higher the chance a move is
imminent (direction still uncertain — sized as a volatility bet, not a call).
"""
from __future__ import annotations

from dataclasses import dataclass

VOLUME_SPIKE = 2.5         # hourly volume above 2.5x its recent average
VOL_EXPANSION = 1.8        # hourly range above 1.8x its recent average
ATTENTION_SURGE = 2.0      # news volume above 2x its recent average
BASIS_SHIFT = 0.5         # basis moved more than 0.5% in the window


@dataclass(frozen=True)
class MoveWarning:
    coin: str
    precursors: int            # how many of the 4 signals are lit
    imminent: bool             # enough precursors to expect a move
    signals: list[str]
    note: str


def detect_move(coin: str, *, volume_ratio: float | None = None,
                range_ratio: float | None = None,
                attention_ratio: float | None = None,
                basis_change_pct: float | None = None) -> MoveWarning:
    """Flag an imminent move from stacked precursors. Direction-agnostic — it
    says a move is COMING and how strong the signal is, not which way."""
    signals = []
    if volume_ratio is not None and volume_ratio >= VOLUME_SPIKE:
        signals.append(f"volume spike {volume_ratio:.1f}x")
    if range_ratio is not None and range_ratio >= VOL_EXPANSION:
        signals.append(f"volatility expanding {range_ratio:.1f}x")
    if attention_ratio is not None and attention_ratio >= ATTENTION_SURGE:
        signals.append(f"news attention surge {attention_ratio:.1f}x")
    if basis_change_pct is not None and abs(basis_change_pct) >= BASIS_SHIFT:
        signals.append(f"basis shift {basis_change_pct:+.1f}%")
    n = len(signals)
    imminent = n >= 2          # 2+ stacked precursors = a real warning
    if imminent:
        note = (f"MOVE IMMINENT — {n}/4 precursors ({', '.join(signals)}); "
                "a move is coming (direction uncertain) — size as a volatility bet")
    elif n == 1:
        note = f"one precursor ({signals[0]}) — watch, not yet a signal"
    else:
        note = "quiet — no move precursors"
    return MoveWarning(coin, n, imminent, signals, note)


def is_move_imminent(w: MoveWarning) -> bool:
    """A tradeable move-warning: 2+ precursors stacked."""
    return w.imminent
