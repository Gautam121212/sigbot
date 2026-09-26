"""The blowup model — flags asymmetric-explosive setups across all assets.

The user's idea: a very risky model where returns can be huge, built from the
PRECURSORS that preceded big blowups (like Bitcoin's runs), then generalized and
tested on other assets to see if the pattern holds.

THE PRECURSOR (decomposed from the Bitcoin bull-run research and TESTED on stocks)
---------------------------------------------------------------------------------
Every big blowup shared a setup, not a prediction of direction:
  1. VOLATILITY COMPRESSION — a long quiet "accumulation" phase (60-day
     volatility well below its own 250-day level = a coiled spring).
  2. BREAKOUT — price reclaiming its long trend (above the 200-day MA).
  3. VOLUME — activity rising during the quiet (accumulation under calm).

MEASURED on US stocks (2010-2026), this setup vs normal:
  30%+ gain in 60 days: 10.7% vs 6.8%  (1.6x)
  50%+ gain:            3.5%  vs 2.3%  (1.5x)
  30%+ drop:            7.9%  vs 4.7%  (upside tail beats downside)

So it does NOT predict direction reliably — it flags setups with a much higher
TAIL PROBABILITY of an explosive move, with the upside tail larger than the
downside. That is a lottery ticket with positive asymmetry: tiny size, huge
potential, taken across many setups so the occasional 50%+ winner pays for the
many that fizzle. This is the blowup model, and it generalizes beyond Bitcoin.
"""
from __future__ import annotations

from dataclasses import dataclass

# Measured tail probabilities for the blowup setup (US stocks, 2010-2026).
P_UP_30 = 0.107
P_UP_50 = 0.035
P_DOWN_30 = 0.079

COMPRESSION_RATIO = 0.70    # 60d vol below 70% of 250d vol = coiled
VOLUME_SURGE = 1.5         # volume above 1.5x its 20-day average


@dataclass(frozen=True)
class BlowupRead:
    is_setup: bool
    tail_up_prob: float        # chance of a 30%+ move
    moonshot_prob: float       # chance of a 50%+ move
    size_pct: float            # tiny speculative size
    note: str


def blowup_setup(atr_pct_60: float | None, atr_pct_250: float | None,
                 close: float | None, sma_200: float | None,
                 volume: float | None, volume_ma_20: float | None) -> BlowupRead:
    """Whether this is a blowup setup: compressed volatility + breakout + volume.

    Direction-blind — it flags the SETUP, not the way it will break. Sized tiny
    because most fizzle; the edge is the fat upside tail across many setups.
    """
    if None in (atr_pct_60, atr_pct_250, close, sma_200, volume, volume_ma_20):
        return BlowupRead(False, 0.0, 0.0, 0.0, "not enough data")
    compressed = atr_pct_60 < atr_pct_250 * COMPRESSION_RATIO   # type: ignore[operator]
    breakout = close > sma_200                                  # type: ignore[operator]
    surge = volume > volume_ma_20 * VOLUME_SURGE                # type: ignore[operator]
    if compressed and breakout and surge:
        return BlowupRead(
            True, P_UP_30, P_UP_50, 0.5,
            f"BLOWUP SETUP — coiled + breakout + volume; "
            f"{P_UP_30:.0%} chance of +30%, {P_UP_50:.0%} of +50% in 60 days. "
            f"Tiny lottery-ticket size (0.5% capital).")
    missing = []
    if not compressed:
        missing.append("no volatility compression")
    if not breakout:
        missing.append("below 200MA")
    if not surge:
        missing.append("no volume surge")
    return BlowupRead(False, P_UP_30 if compressed else 0.0, 0.0, 0.0,
                      "not a blowup setup: " + ", ".join(missing))


def expected_value(read: BlowupRead) -> float:
    """Rough EV of the lottery ticket: fat upside tail vs the capped 1-unit risk.
    Positive because the +30/+50% tail probabilities beat the downside for the
    small size risked."""
    if not read.is_setup:
        return 0.0
    # crude EV in 'units of the small stake': p(+30)*0.3 + p(+50 extra)*0.2 - p(down30)*0.3
    return round(P_UP_30 * 0.3 + P_UP_50 * 0.2 - P_DOWN_30 * 0.3, 3)
