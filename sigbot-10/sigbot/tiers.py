"""Alert tiers and failure classification.

This module replaces the calendar-based "learning phase" idea with an
evidence-based one, for a reason worth stating plainly: **how long the bot has
been running tells you nothing about whether a signal is trustworthy.** An
asset with 200 resolved observations on day 40 is better evidenced than one
with 12 observations on day 400. Tier is a property of the evidence, not of
the clock.

The sample-size floors below are derived, not chosen. At 90% confidence:

    observed 65% needs n >=  27 for a lower bound >= 50%
    observed 65% needs n >=  61 for a lower bound >= 55%
    observed 65% needs n >= 244 for a lower bound >= 60%
    observed 70% needs n >=  58 for a lower bound >= 60%

Which is why a "40 observations, 60% gate" tier cannot exist: 40 observations
at an observed 70% hit rate gives a lower bound of 57.1%. To make such a tier
fire you would have to lower the gate to meet the evidence, and a gate that
moves to accommodate the answer is not a gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .stats import wilson_interval


class Tier(str, Enum):
    SILENT = "SILENT"      # not enough evidence to say anything
    WATCH = "WATCH"        # measurable, weak. paper only
    CAUTION = "CAUTION"    # holds up at 55%. reduced size
    TRADE = "TRADE"        # holds up at 60%

    @property
    def label(self) -> str:
        return {
            Tier.SILENT: "COLLECTING — no alert",
            Tier.WATCH: "WEAK EVIDENCE — paper trade only",
            Tier.CAUTION: "BUILDING — reduced size only",
            Tier.TRADE: "EVIDENCED — all gates pass on measured data",
        }[self]


@dataclass(frozen=True)
class TierRule:
    tier: Tier
    min_observations: int
    min_lower_bound: float


# Ordered strongest first. Floors are derived above, not tuned.
TIER_RULES = (
    TierRule(Tier.TRADE, 150, 0.60),
    TierRule(Tier.CAUTION, 60, 0.55),
    TierRule(Tier.WATCH, 25, 0.50),
)


def classify_tier(n_resolved: int, n_hits: float, conf: float = 0.90) -> tuple[Tier, float]:
    """Return (tier, wilson_lower_bound) for an asset/model's track record.

    Nothing here can be overridden at runtime. A tier is earned by the record
    or it is not reached.
    """
    if n_resolved <= 0:
        return Tier.SILENT, 0.0
    lower, _ = wilson_interval(n_hits, n_resolved, conf)
    for rule in TIER_RULES:
        if n_resolved >= rule.min_observations and lower >= rule.min_lower_bound:
            return rule.tier, float(lower)
    return Tier.SILENT, float(lower)


def observations_needed(tier: Tier, observed_rate: float, conf: float = 0.90,
                        cap: int = 20000) -> int | None:
    """How many observations at `observed_rate` would reach `tier`.

    Used to tell the user honestly how far away a tier is instead of implying
    it arrives on a schedule. Returns None if unreachable at that rate.
    """
    rule = next((r for r in TIER_RULES if r.tier is tier), None)
    if rule is None:
        return None
    n = max(rule.min_observations, 5)
    while n <= cap:
        if wilson_interval(round(observed_rate * n), n, conf)[0] >= rule.min_lower_bound:
            return n
        n += 1
    return None


# --------------------------------------------------------------- failures

class Failure(str, Enum):
    """Only outcomes derivable from the price path are listed.

    Deliberately omitted: "news conflict", "low liquidity", "random". Those
    cannot be distinguished from OHLC data, so a system that logged them would
    be recording a guess and then treating the guess as evidence. Anything the
    price path cannot explain is UNEXPLAINED, and the honest response to a rising
    UNEXPLAINED count is that the model has no edge here, not that it needs a
    new category.
    """

    WIN = "win"
    MAGNITUDE_SHORT = "magnitude_short"   # right way, move smaller than costs
    DIRECTION_WRONG = "direction_wrong"   # wrong way, never favourable
    REVERSAL = "reversal"                 # went favourable, closed adverse
    GAP_AGAINST = "gap_against"           # opened past the adverse threshold
    UNEXPLAINED = "unexplained"


def classify_outcome(
    side: str,
    entry: float,
    bar_open: float | None,
    bar_high: float | None,
    bar_low: float | None,
    bar_close: float,
    cost_pct: float = 0.0015,
    favourable_excursion: float = 0.005,
) -> tuple[Failure, float]:
    """Classify one resolved prediction from the outcome bar. Returns (mode, net)."""
    if entry <= 0:
        return Failure.UNEXPLAINED, 0.0

    sign = 1.0 if side == "BUY" else -1.0
    net = sign * (bar_close / entry - 1.0) - cost_pct

    if net > 0:
        return Failure.WIN, net

    if bar_open is not None and bar_open > 0:
        gap = sign * (bar_open / entry - 1.0)
        if gap <= -favourable_excursion:
            return Failure.GAP_AGAINST, net

    if bar_high is not None and bar_low is not None:
        best = sign * ((bar_high if sign > 0 else bar_low) / entry - 1.0)
        if best >= favourable_excursion:
            return Failure.REVERSAL, net

    raw = sign * (bar_close / entry - 1.0)
    if raw > 0:
        return Failure.MAGNITUDE_SHORT, net
    if raw < 0:
        return Failure.DIRECTION_WRONG, net
    return Failure.UNEXPLAINED, net


def render_track_record(
    symbol: str, model: str, n: int, hits: float,
    failures: dict[str, int] | None = None, conf: float = 0.90,
) -> str:
    tier, lower = classify_tier(n, hits, conf)
    rate = hits / n if n else float("nan")
    lines = [
        f"{symbol} · {model} — {tier.value}: {tier.label}",
        f"  {n} resolved, hit rate {rate:.1%}, {conf:.0%} lower bound {lower:.1%}",
    ]
    if tier is not Tier.TRADE and n:
        need = observations_needed(Tier.TRADE, rate, conf)
        lines.append(
            f"  at this rate, TRADE tier needs ~{need} checks"
            if need else
            "  at this rate TRADE tier is unreachable — the hit rate itself is too low"
        )
    if failures:
        ordered = sorted(failures.items(), key=lambda kv: -kv[1])
        lines.append("  outcomes: " + ", ".join(f"{k} {v}" for k, v in ordered))
    return "\n".join(lines)
