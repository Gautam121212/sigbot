"""Crypto risk signals — the edge the direction models never had.

LEVERAGE-CROWDING (the confirmed one)
-------------------------------------
Every crypto DIRECTION model this project tested came back with no edge:
momentum, mean-reversion, breakouts all failed. The gap was that none looked
at POSITIONING — how crowded leverage is — only at price.

This measures a reachable proxy for crowded leverage: realized volatility
RISING while price goes nowhere. Volatility building without the price moving
is consistent with leverage stacking on both sides before a squeeze. Tested on
8-10 major coins over the past year, confirmed in BOTH halves independently:

    next 5 days, crowded state   -1.29% avg, fell 64% of the time
    calm state (vol falling)     +0.35% avg, fell 53%
    both halves separately       crowded worse than calm in each

It is an AVOID / EXIT signal, not a buy signal: when crowded, a long is more
likely to fall, so the model stands aside or trims. Honest limits: one year of
data, a proxy for real funding-rate/open-interest data no connected source
provides, and a modest edge (~1-2% over 5 days) — enough to gate risk, not to
trade on alone.
"""
from __future__ import annotations

from dataclasses import dataclass

VOL_WINDOW = 10
LOWVOL_DROP_PCT = -0.03      # a 3%+ down day
LOWVOL_RATIO = 0.8          # volume below 80% of its 20-day average
VOL_RISE_RATIO = 1.3        # volatility now vs 10 days ago
FLAT_PRICE_MAX = 0.05       # price moved less than 5% over the window


@dataclass(frozen=True)
class CrowdingRead:
    crowded: bool
    vol_now: float
    vol_prev: float
    price_drift: float
    reason: str


def _returns(closes) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def _vol(returns, end: int, window: int = VOL_WINDOW) -> float | None:
    """Std of returns over the window ending at index `end` (in returns space)."""
    if end < window - 1 or end >= len(returns):
        return None
    seg = returns[end - window + 1:end + 1]
    m = sum(seg) / len(seg)
    return (sum((r - m) ** 2 for r in seg) / len(seg)) ** 0.5


def read_crowding(closes) -> CrowdingRead:
    """Is leverage crowded (vol rising, price flat) on the latest bar?

    Needs about 2*VOL_WINDOW+1 closes. Too few -> not crowded, stated.
    """
    if closes is None or len(closes) < 2 * VOL_WINDOW + 2:
        return CrowdingRead(False, 0.0, 0.0, 0.0, "not enough history to read crowding")
    rets = _returns(closes)
    vol_now = _vol(rets, len(rets) - 1)
    vol_prev = _vol(rets, len(rets) - 1 - VOL_WINDOW)
    if vol_now is None or vol_prev is None or vol_prev == 0:
        return CrowdingRead(False, 0.0, 0.0, 0.0, "volatility unreadable")
    drift = abs(closes[-1] / closes[-1 - VOL_WINDOW] - 1)
    crowded = vol_now > vol_prev * VOL_RISE_RATIO and drift < FLAT_PRICE_MAX
    reason = (f"leverage crowded — volatility up {vol_now / vol_prev:.1f}x while "
              f"price flat ({drift:.1%}); falls more likely, stand aside"
              if crowded else
              f"not crowded (vol {vol_now / vol_prev:.1f}x, drift {drift:.1%})")
    return CrowdingRead(crowded, round(vol_now, 5), round(vol_prev, 5),
                        round(drift, 4), reason)


def low_volume_drop_reversal(closes, volumes) -> tuple[bool, str]:
    """A 3%+ down day on BELOW-average volume — a quiet drop that tends to
    rebound in crypto.

    Confirmed on 14 major coins, both halves independently: after a low-volume
    3%+ drop, the next 3 days averaged +1.77% and +1.69% (vs baseline -0.30%).
    The OPPOSITE of the stock market, where high-volume capitulation is the
    buy — here a quiet drop reverses, a loud one keeps falling. A BUY signal,
    unlike crowding (an avoid signal).

    Honest limit: the high-volume half of the pattern did NOT confirm (it
    flipped sign between halves), so only the low-volume-rebound half is used.
    """
    if closes is None or volumes is None or len(closes) < 22 or len(volumes) < 22:
        return False, "not enough history"
    day_ret = closes[-1] / closes[-2] - 1
    vma = sum(volumes[-21:-1]) / 20
    if day_ret <= LOWVOL_DROP_PCT and vma > 0 and volumes[-1] < vma * LOWVOL_RATIO:
        return True, (f"quiet {day_ret:.1%} drop on low volume "
                      f"({volumes[-1] / vma:.0%} of average) — tends to rebound")
    return False, "not a low-volume drop"


MA7_DIP_PCT = 0.90          # price at or below 90% of its 7-day average


def below_ma7_dip(closes, volumes=None) -> tuple[bool, str]:
    """Price 10%+ below its 7-day average — a sharp dip that rebounds in crypto
    (+2.72% / +0.33% both halves). Same mean-reversion family as the low-volume
    drop, so they are made MUTUALLY EXCLUSIVE.

    COLLISION GUARD: if the low-volume-drop signal already fires on this bar
    (a 3%+ down day on below-average volume), this one stands down and returns
    False — the drop signal owns that bar. This one only adds the cases where
    price is stretched below its average WITHOUT that specific down-day-on-low-
    volume pattern, so no bar is ever counted by both.
    """
    if closes is None or len(closes) < 8:
        return False, "not enough history"
    ma7 = sum(closes[-7:]) / 7
    if ma7 <= 0 or closes[-1] > ma7 * MA7_DIP_PCT:
        return False, "not stretched below the 7-day average"
    # Collision guard: yield to the low-volume-drop signal if it owns this bar.
    if volumes is not None and low_volume_drop_reversal(closes, volumes)[0]:
        return False, "deferred to the low-volume-drop signal (same bar)"
    return True, f"{closes[-1] / ma7 - 1:.1%} below the 7-day average — tends to rebound"
