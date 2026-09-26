"""Pre-earnings drift — a leading news signal from the professional playbook.

Event-driven pros: "stocks drift in the direction of their eventual earnings
surprise in the 2-3 weeks BEFORE the report" — informed participants (insiders,
analysts) position before the number drops. Unlike post-earnings drift (which is
largely arbitraged away), this is a LEADING signal.

MEASURED (US stocks, 2009-2026): a 3%+ pre-earnings move predicts the surprise
direction 54-55% of the time — in ALL THREE periods, on 8,000-17,000 events.
Modest (54% vs 50%) but stable and leading, which is rare.

Use: when a stock has drifted before its upcoming earnings, lean the same way —
a small edge over a coin flip, sized small (it is 54%, not 70%). It pairs with
the confirmed-surprise signal (which fires AFTER the report): pre-drift positions
before, confirmed-surprise confirms after.
"""
from __future__ import annotations

# The measured hit rate of pre-drift predicting the surprise, by period.
PREDRIFT_HIT = {"C2 09-15": 0.55, "D 16-20": 0.55, "C1 21+": 0.54}
MIN_DRIFT = 0.03            # need at least a 3% pre-move to read as positioning


def pre_earnings_lean(price_now: float | None, price_10d_ago: float | None
                      ) -> str | None:
    """The direction to lean into an upcoming earnings report, from the stock's
    pre-earnings drift. None if the drift is too small to read."""
    if price_now is None or price_10d_ago is None or price_10d_ago <= 0:
        return None
    drift = price_now / price_10d_ago - 1
    if drift >= MIN_DRIFT:
        return "BUY"           # drifting up before earnings -> lean beat
    if drift <= -MIN_DRIFT:
        return "SELL"          # drifting down -> lean miss
    return None                # too flat to read


def expected_hit_rate() -> float:
    """The signal's edge over a coin flip — small but stable (~54.5%)."""
    return sum(PREDRIFT_HIT.values()) / len(PREDRIFT_HIT)
