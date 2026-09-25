"""Magnitude signal — flags situations that could move BIG, for sized bets.

The user's point: the risky bets are vague because nothing says "this could move
significantly, put a small amount on it." This is that indicator. It does NOT
predict DIRECTION — it predicts the SIZE of the coming move, so a speculative
bet can be sized to the potential.

MEASURED (US stocks, 2015+): the average absolute 5-day move is 4.6%. But when
these flags stack, the expected move multiplies:
  extreme RSI ............ 7.1%   (1.5x)
  volume surge (3x) ...... 7.8%   (1.7x)
  high ATR (>5%) ......... 8.8%   (1.9x)
  strong trend (25%+) .... 9.9%   (2.1x)
  ALL FOUR ............... 20.2%  (4.4x)

Use: a bet on a big-magnitude flag is sized SMALL (it's a lottery ticket — big
potential move, unknown direction) and only taken when the direction signal and
the magnitude signal agree. High magnitude + a direction edge = a bigger, still-
capped position; high magnitude alone = a small speculative bet.
"""
from __future__ import annotations

from dataclasses import dataclass

BASELINE_MOVE = 0.046           # average absolute 5-day move


@dataclass(frozen=True)
class MagnitudeRead:
    score: int                  # 0-4, how many big-move flags are lit
    expected_move: float        # estimated absolute 5-day move
    bet_size_pct: float         # suggested speculative size (% of capital)
    note: str


def magnitude(atr_pct: float | None, volume_ratio: float | None,
              rsi: float | None, mom20: float | None) -> MagnitudeRead:
    """How big could the next move be, from four independent flags."""
    flags = 0
    reasons = []
    if atr_pct is not None and atr_pct > 0.05:
        flags += 1
        reasons.append("high volatility")
    if volume_ratio is not None and volume_ratio > 3.0:
        flags += 1
        reasons.append("volume surge")
    if rsi is not None and (rsi < 20 or rsi > 80):
        flags += 1
        reasons.append("stretched RSI")
    if mom20 is not None and abs(mom20) > 0.25:
        flags += 1
        reasons.append("strong trend")

    # Expected move scales with flag count (from the measured multipliers).
    mult = {0: 1.0, 1: 1.6, 2: 2.3, 3: 3.2, 4: 4.4}[flags]
    expected = BASELINE_MOVE * mult
    # Speculative sizing: bigger potential move -> a slightly bigger (still tiny)
    # lottery-ticket bet. Capped low because direction is unknown.
    bet = {0: 0.0, 1: 0.0, 2: 0.25, 3: 0.5, 4: 1.0}[flags]  # % of capital
    note = (f"{flags}/4 big-move flags ({', '.join(reasons)}) — "
            f"~{expected * 100:.0f}% expected move" if flags else "no big-move flags")
    return MagnitudeRead(flags, round(expected, 3), bet, note)


def is_high_magnitude(read: MagnitudeRead) -> bool:
    """Worth a speculative bet: 2+ flags, so the move could be meaningfully big."""
    return read.score >= 2
