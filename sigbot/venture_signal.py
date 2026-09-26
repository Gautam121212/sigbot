"""Venture structural signal — the fundamental characteristics of big winners.

The user was right that I never explored the venture STRUCTURAL edge for lack of
data. But Shibui has fundamentals (revenue growth, margins, ROIC), so the
venture question — which companies have the characteristics that precede
outsized returns — IS testable. The power-law model had the portfolio math but
no SIGNAL for which companies to bet on. This is that signal.

MEASURED (US stocks, 2012-2026, survivorship-accounted, SEC-filing-gated):
Revenue growth predicts the chance of DOUBLING within a year, monotonically:
  hypergrowth (40%+ YoY): 8.6% doubled
  fast (15-40%):          5.8%
  modest (0-15%):         3.4%
A 2.5x lift from growth alone.

THE COUNTERINTUITIVE PART (from decomposing the mechanism): among hypergrowth
companies, the CASH-BURNING ones double MORE often (11.8% / 10.4% across eras)
than the profitable ones (5.6% / 5.2%). The biggest winners are aggressive,
unprofitable, growth-at-all-costs companies reinvesting everything — NOT safe
profitable growers. This is exactly the VC power law: bet on the outlier's
growth, not steady earnings. A profitable hypergrowth company has already
matured; a cash-burning one still has the explosive phase ahead.

So the venture signal is: hypergrowth revenue + NOT yet profitable = the
highest chance of an outlier. Sized tiny (power-law bet), taken across many
(20+ for the portfolio math), which the power_law model already enforces.
"""
from __future__ import annotations

from dataclasses import dataclass

# Measured double-rates by revenue growth (survivorship-accounted).
DOUBLE_RATE = {"hypergrowth": 0.086, "fast": 0.058, "modest": 0.034}
# Among hypergrowth, cash-burning doubles more (the outlier profile).
HYPERGROWTH_BURNING_DOUBLE = 0.11    # ~11% across eras
HYPERGROWTH_PROFITABLE_DOUBLE = 0.055

# The fuller research pass found hypergrowth + HIGH GROSS MARGIN (software-like
# economics) is the best profile: 9.4% double-rate, vs 8.6% hypergrowth-alone.
# Quality metrics (Piotroski 8-9, high ROIC) predict LESS doubling (3.1%, 4.4%)
# — safe quality is the wrong signal for outliers.
HIGH_GROSS_MARGIN = 0.60   # keeps most of each revenue dollar
HYPERGROWTH = 0.40         # 40%+ YoY revenue growth
FAST_GROWTH = 0.15
PROFITABLE_MARGIN = 0.10   # operating margin above this = already mature


@dataclass(frozen=True)
class VentureSignal:
    is_candidate: bool
    double_probability: float   # chance of doubling in a year
    profile: str
    note: str


def venture_signal(revenue_growth_yoy: float | None,
                   operating_margin: float | None,
                   gross_margin: float | None = None) -> VentureSignal:
    """The venture structural read: does this company have the outlier profile?

    Strongest profile (fuller pass): hypergrowth + high gross margin (9.4%).
    """
    if revenue_growth_yoy is None:
        return VentureSignal(False, 0.0, "unknown", "no growth data")
    if (revenue_growth_yoy >= HYPERGROWTH and gross_margin is not None
            and gross_margin >= HIGH_GROSS_MARGIN):
        return VentureSignal(
            True, 0.094, "hypergrowth high-margin",
            f"{revenue_growth_yoy:.0%} growth + {gross_margin:.0%} gross margin — "
            "software-like economics, the strongest outlier profile (9.4% double-rate)")
    if revenue_growth_yoy < FAST_GROWTH:
        return VentureSignal(False, DOUBLE_RATE["modest"], "slow",
                             "growth too slow for an outlier bet")
    if revenue_growth_yoy >= HYPERGROWTH:
        # the strongest profile: hypergrowth AND still burning cash
        if operating_margin is not None and operating_margin < PROFITABLE_MARGIN:
            return VentureSignal(
                True, HYPERGROWTH_BURNING_DOUBLE, "hypergrowth cash-burning",
                f"{revenue_growth_yoy:.0%} growth, not yet profitable — the "
                f"outlier profile ({HYPERGROWTH_BURNING_DOUBLE:.0%} double-rate); "
                "small power-law bet")
        return VentureSignal(
            True, HYPERGROWTH_PROFITABLE_DOUBLE, "hypergrowth profitable",
            f"{revenue_growth_yoy:.0%} growth but already profitable — the "
            "explosive phase may be behind it; smaller bet")
    return VentureSignal(True, DOUBLE_RATE["fast"], "fast-growth",
                         f"{revenue_growth_yoy:.0%} growth — a moderate candidate")


def is_outlier_candidate(sig: VentureSignal) -> bool:
    """The top venture profile worth a power-law bet."""
    return sig.profile == "hypergrowth cash-burning"
