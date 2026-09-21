"""The research protocol: how a pattern earns a place in sigbot.

WHY CONFIDENCE DOES NOT RISE JUST BY TESTING MORE
-------------------------------------------------
Test 38 indicators and, at the usual 5% bar, about two look significant by
chance alone. Test 500 and about twenty-five do — and those are exactly the
ones that fail live. More data does not fix that; it makes it easier to find
patterns that were never there. What fixes it is how the testing is done:

1. PRE-REGISTER. Every hypothesis is written down (here) before its result
   is seen, with its horizon and its direction.
2. DISCOVER ON ONE PERIOD, CONFIRM ON TWO OTHERS. Discovery 2016-20;
   confirmation 2021 onward and 2009-15, never used to choose anything.
3. CORRECT FOR THE NUMBER OF TESTS. Discovery must clear a Bonferroni bar
   for the size of the batch; each confirmation must keep the same sign with
   t >= 2.

What the first full sweep taught: most indicator edges FLIP SIGN between
periods (MACD crossovers +0.33% then -0.24%; bullish engulfing +0.19% then
-0.20%) because each period mixes market regimes differently. Tested within
regimes, oversold signals were consistent in all three periods only during
volatile market declines — which became the capitulation setup.

Honest limits, recorded rather than hidden: t-statistics here overstate
certainty, because the same stock is measured on overlapping days and panics
make many stocks fire together; and the regime split was a second round of
testing after the first sweep.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt


@dataclass(frozen=True)
class Result:
    hypothesis: str
    discovery_t: float        # 2016-20
    confirm_recent_t: float   # 2021 onward
    confirm_early_t: float    # 2009-15
    excess_pct: tuple[float, float, float]   # same order, beyond the index


def bonferroni_t(batch_size: int, alpha: float = 0.05) -> float:
    """The |t| a discovery must clear when `batch_size` tests were run."""
    p = alpha / max(1, batch_size)
    lo, hi = 0.0, 10.0          # two-sided normal quantile by bisection
    for _ in range(60):
        mid = (lo + hi) / 2
        tail = 1 - erf(mid / sqrt(2))
        lo, hi = (mid, hi) if tail > p else (lo, mid)
    return round(hi, 2)


def survives(r: Result, batch_size: int) -> bool:
    """Discovery clears the corrected bar; both confirmations agree in sign
    with t >= 2."""
    bar = bonferroni_t(batch_size)
    if abs(r.discovery_t) < bar:
        return False
    sign = 1 if r.discovery_t > 0 else -1
    return all(sign * t >= 2.0 for t in (r.confirm_recent_t, r.confirm_early_t))


# The first pre-registered sweep: 38 conditions, 10-day excess over the index.
# A selection is kept here — the survivor, the near-misses, and the flips that
# explain why confidence cannot simply be raised by testing more.
SWEEP_1_BATCH = 38
SWEEP_1 = (
    Result("Williams %R below -90", 3.4, 3.2, 10.5, (0.099, 0.082, 0.239)),
    Result("Money flow (CMF) below -0.2", 14.7, 1.8, 8.0, (0.462, 0.369, 0.233)),
    Result("Stochastic below 20", 5.3, 1.0, 11.1, (0.115, 0.047, 0.192)),
    Result("MACD crosses up", 8.5, -5.6, 1.5, (0.333, -0.243, 0.043)),
    Result("Bullish engulfing candle", 4.7, -4.6, 3.8, (0.194, -0.198, 0.125)),
    Result("Aroon oscillator below -50", 15.7, -2.4, 10.0, (0.262, -0.037, 0.140)),
    Result("RSI below 30", -4.8, 11.9, 1.1, (-0.244, 0.470, 0.053)),
    Result("Rate of change above +15%", 15.5, -0.0, 9.5, (1.118, -0.006, 0.615)),
)

# Second round, within regimes: oversold signals during a VOLATILE DECLINE
# (index below its 200-day average and 20-day volatility above its median).
REGIME_BATCH = 16
REGIME_ROUND = (
    Result("Williams %R < -90 | volatile decline", 2.0, 11.9, 10.0, (0.15, 0.61, 0.56)),
    Result("Stochastic < 20 | volatile decline", 2.2, 16.4, 10.5, (0.13, 0.64, 0.45)),
    Result("CMF < -0.2 | volatile decline", 11.1, 3.2, 8.7, (0.88, 2.92, 0.68)),
    Result("Williams %R < -90 | calm rise", 3.9, -4.5, 0.4, (0.12, -0.16, 0.01)),
)

# Round 3: the three hypotheses written down before round 2's results were
# known. Tested as a batch of 3 (discovery bar |t| >= 2.39).
ROUND_3_BATCH = 3
ROUND_3 = (
    # Adopted: capitulation now holds 20 days.
    Result("Capitulation held 20 days (vs 5 and 10)", 10.3, 9.0, 13.9, (1.04, 0.62, 1.09)),
    # Failed: in liquid stocks insider cluster buying added nothing in any
    # period. In smaller stocks it did (+1.84% / +0.22% / +1.37%) but faded
    # after 2020 and the median trade lost — the leftover edge of a widely
    # watched signal sits where large funds cannot trade.
    Result("Insider cluster buying, liquid stocks, 20 days", 0.1, 0.3, 1.0, (0.06, 0.17, 0.65)),
    # Failed: the sign flips between periods, and 2021+ is a few outliers.
    Result("Earnings big miss in a volatile decline, 20 days", 3.1, 1.0, -2.1, (2.72, 11.28, -1.97)),
)

# Written down BEFORE testing, so their results cannot shape their wording.
PENDING = (
    "Capitulation only when the stock's whole sector also fell (market-wide "
    "panic, not company news) -> 20-day excess, all three periods",
    "Capitulation position size scaled by how volatile the decline is -> "
    "return per unit of risk, all three periods",
)


def summary() -> str:
    lines = [f"Sweep 1 — {SWEEP_1_BATCH} pre-registered conditions "
             f"(discovery bar |t| >= {bonferroni_t(SWEEP_1_BATCH)})", ""]
    for r in SWEEP_1:
        verdict = "SURVIVES" if survives(r, SWEEP_1_BATCH) else "fails"
        e = ", ".join(f"{x:+.2f}%" for x in r.excess_pct)
        lines.append(f"  {verdict:<9} {r.hypothesis:<34} {e}")
    lines += ["", "Within regimes:"]
    for r in REGIME_ROUND:
        consistent = all(x > 0 for x in r.excess_pct) or all(x < 0 for x in r.excess_pct)
        e = ", ".join(f"{x:+.2f}%" for x in r.excess_pct)
        lines.append(f"  {'CONSISTENT' if consistent else 'flips':<10} {r.hypothesis:<40} {e}")
    lines += ["", f"Round 3 — the pre-registered hypotheses (batch of {ROUND_3_BATCH}):"]
    for r in ROUND_3:
        verdict = "SURVIVES" if survives(r, ROUND_3_BATCH) else "fails"
        e = ", ".join(f"{x:+.2f}%" for x in r.excess_pct)
        lines.append(f"  {verdict:<9} {r.hypothesis:<50} {e}")
    lines += ["", "Pre-registered for the next round:"] + [f"  - {h}" for h in PENDING]
    return "\n".join(lines)
