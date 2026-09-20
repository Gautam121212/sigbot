"""Expectancy, skill, and sizing — the module that should have come first.

You asked for a 70% win rate at two trades a week. That target is satisfiable
in about a minute, and satisfying it proves nothing. This module exists to make
that visible and then to give you the thing you actually need instead.

## A 70% win rate requires no predictive skill

On a driftless random walk, the probability of touching +R before -1R is
exactly 1/(1+R). So the win rate is a **dial you set with your exit geometry**,
not a measure of anything:

        target      win rate on pure noise      expectancy
         2.00R                33.3%                 0
         1.50R                40.0%                 0
         1.00R                50.0%                 0
         0.60R                62.5%                 0
         0.43R                69.9%                 0
         0.30R                76.9%                 0

Set the target to 0.43R and you have your 70%, today, with zero edge and zero
expected profit. Simulation over 30,000 barrier races reproduces the closed
form to within a point. This is not an obscure result: an independent study
entered roughly 900,000 zero-skill trades on twelve years of NQ futures and
constructed a 99% win rate that still lost money, in five minutes.

Breakeven win rate is also 1/(1+R). The same number. That identity is the whole
argument: at any geometry, the win rate you get for free is exactly the win rate
you need to break even. **Everything above it is skill; nothing below it is.**

## So what does your spec actually require?

    target R   mechanical WR   skill needed to reach 70%   EV at 70%
      0.43R        69.9%                 0.1pp              +0.001R
      0.60R        62.5%                 7.5pp              +0.120R
      0.75R        57.1%                12.9pp              +0.225R
      1.00R        50.0%                20.0pp              +0.400R

A profitable 70% system is one that beats its own geometry. At a 0.75R target
that means being right 12.9 points more often than a coin — which is a large
edge, larger than most documented anomalies survive at after costs.

## And how long to know whether you have it?

Two-proportion test, 80% power, one-sided alpha 0.05, at two trades per week:

      target 0.50R -> 2,407 trades = 23.1 years
      target 0.60R ->   491 trades =  4.7 years
      target 0.75R ->   172 trades =  1.7 years
      target 1.00R ->    73 trades =  0.7 years

This is the real cost of low frequency, and it points the opposite way from
intuition: **a wider target needs fewer trades to validate**, because the skill
gap it demands is larger and therefore easier to detect. Two trades a week at a
tight target is a design that cannot be evaluated within your lifetime.

Trend-following CTAs run 35-48% win rates with strong positive expectancy;
market-makers run 70-85% on tiny margins; option sellers run 80-90% with
occasional catastrophic losses. None of those numbers is comparable to another.
Only expectancy is.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np

from .stats import wilson_interval


# ------------------------------------------------------- geometry vs skill

def mechanical_win_rate(target_r: float) -> float:
    """P(touch +target_r before -1R) on a driftless walk. Also the breakeven rate.

    These being the same number is the point: the win rate your geometry hands
    you for free is exactly the win rate you need to break even.
    """
    if target_r <= 0:
        raise ValueError("target_r must be positive")
    return 1.0 / (1.0 + target_r)


def breakeven_win_rate(target_r: float) -> float:
    return mechanical_win_rate(target_r)


def expectancy_r(win_rate: float, target_r: float) -> float:
    """Expected R per trade, before costs."""
    return win_rate * target_r - (1.0 - win_rate)


def skill_edge(observed_win_rate: float, target_r: float) -> float:
    """Win rate above what the geometry gives for free. The only honest metric.

    A 70% win rate at a 0.43R target is 0.1pp of skill. The same 70% at a 1.0R
    target is 20pp. Reporting the 70% alone conflates them.
    """
    return observed_win_rate - mechanical_win_rate(target_r)


def target_for_win_rate(win_rate: float) -> float:
    """Inverse of the dial: the target that mechanically produces this win rate."""
    if not 0 < win_rate < 1:
        raise ValueError("win_rate must be strictly between 0 and 1")
    return (1.0 - win_rate) / win_rate


# ------------------------------------------------------------ sample sizes

def trades_to_detect(observed: float, baseline: float,
                     power: float = 0.80, alpha: float = 0.05) -> float:
    """Trades needed to distinguish `observed` from `baseline`, one-sided.

    Use `baseline = mechanical_win_rate(target_r)`, never 0.50 — beating a coin
    is not the bar when your geometry already beats a coin.
    """
    if observed <= baseline:
        return float("inf")
    z_a = {0.10: 1.2816, 0.05: 1.6449, 0.01: 2.3263}.get(round(alpha, 2), 1.6449)
    z_b = {0.80: 0.8416, 0.90: 1.2816, 0.95: 1.6449}.get(round(power, 2), 0.8416)
    p = (observed + baseline) / 2.0
    num = z_a * sqrt(2 * p * (1 - p)) + z_b * sqrt(
        observed * (1 - observed) + baseline * (1 - baseline)
    )
    return float((num / (observed - baseline)) ** 2)


def years_to_validate(observed: float, target_r: float,
                      trades_per_week: float = 2.0) -> float:
    n = trades_to_detect(observed, mechanical_win_rate(target_r))
    return float("inf") if not np.isfinite(n) else n / (trades_per_week * 52.0)


# ---------------------------------------------------------------- sizing

def kelly_fraction(win_rate: float, target_r: float) -> float:
    """Full-Kelly fraction of capital to risk. Clipped at zero for no edge."""
    if target_r <= 0:
        raise ValueError("target_r must be positive")
    f = (target_r * win_rate - (1.0 - win_rate)) / target_r
    return float(max(0.0, f))


@dataclass(frozen=True)
class SizingAdvice:
    win_rate: float
    win_rate_lower: float
    target_r: float
    n_observations: int
    full_kelly: float
    conservative_kelly: float
    recommended_risk_pct: float
    note: str

    def render(self) -> str:
        return (
            f"observed {self.win_rate:.1%} over {self.n_observations} trades "
            f"(90% lower bound {self.win_rate_lower:.1%}) at a {self.target_r:.2f}R target\n"
            f"  skill above geometry: {skill_edge(self.win_rate, self.target_r):+.1%}\n"
            f"  expectancy: {expectancy_r(self.win_rate, self.target_r):+.3f}R per trade\n"
            f"  full Kelly on the point estimate: {self.full_kelly:.1%}\n"
            f"  quarter Kelly on the LOWER BOUND: {self.conservative_kelly:.1%}\n"
            f"  recommended risk per trade: {self.recommended_risk_pct:.2f}%\n"
            f"  {self.note}"
        )


def size_position(n_trades: int, n_wins: int, target_r: float,
                  kelly_divisor: float = 4.0, hard_cap_pct: float = 2.0,
                  conf: float = 0.90) -> SizingAdvice:
    """Kelly sizing computed on the lower bound, not the point estimate.

    Kelly consumes your *estimate* of p, and the estimate is noisy. At n=100
    with 70% observed, the 90% interval runs roughly 62%-77%; at a 0.75R target
    that is full-Kelly 11.3% versus 46.3% — a factor of four. Sizing on the
    point estimate systematically overbets, and overbetting Kelly produces
    drawdowns that end accounts before the edge can pay.

    So: quarter-Kelly on the lower bound, hard-capped, and zero until there is
    enough evidence to compute a bound worth using.
    """
    if n_trades <= 0:
        return SizingAdvice(float("nan"), 0.0, target_r, 0, 0.0, 0.0, 0.0,
                            "no trades yet — risk nothing")
    wr = n_wins / n_trades
    lower, _ = wilson_interval(n_wins, n_trades, conf)
    full = kelly_fraction(wr, target_r)
    conservative = kelly_fraction(lower, target_r) / kelly_divisor
    mech = mechanical_win_rate(target_r)

    if n_trades < 30:
        rec, note = 0.0, (f"{n_trades} trades is not an estimate. Paper only.")
    elif lower <= mech:
        rec, note = 0.0, (
            f"the {conf:.0%} lower bound {lower:.1%} does not clear the "
            f"{mech:.1%} your geometry gives free. No demonstrated skill — risk nothing."
        )
    else:
        rec = min(conservative * 100.0, hard_cap_pct)
        note = (f"lower bound clears geometry by {lower - mech:+.1%}. "
                f"Capped at {hard_cap_pct:.1f}% regardless of what Kelly says.")
    return SizingAdvice(wr, float(lower), target_r, n_trades, full,
                        float(conservative), float(rec), note)


# ------------------------------------------------------------- diagnostics

def geometry_table(targets=(0.30, 0.43, 0.60, 0.75, 1.00, 1.50, 2.00, 3.00)) -> str:
    rows = ["  target   free WR   breakeven   EV@70%WR   trades to prove 70%"]
    for R in targets:
        m = mechanical_win_rate(R)
        n = trades_to_detect(0.70, m)
        n_txt = "never" if not np.isfinite(n) else f"{n:,.0f}"
        rows.append(f"  {R:>6.2f}   {m:>7.1%}   {m:>9.1%}   {expectancy_r(0.70, R):>+8.3f}R"
                    f"   {n_txt:>19}")
    return "\n".join(rows)


def audit(observed_win_rate: float, target_r: float, n_trades: int) -> str:
    """One-screen verdict on whether a reported win rate means anything."""
    mech = mechanical_win_rate(target_r)
    edge = observed_win_rate - mech
    lower, _ = wilson_interval(round(observed_win_rate * n_trades), n_trades, 0.90)
    lines = [
        f"reported: {observed_win_rate:.1%} over {n_trades} trades at {target_r:.2f}R",
        f"  geometry alone gives {mech:.1%} of that",
        f"  claimed skill: {edge:+.1%}",
        f"  expectancy: {expectancy_r(observed_win_rate, target_r):+.3f}R per trade",
        f"  90% lower bound on the win rate: {lower:.1%}",
    ]
    if edge <= 0:
        lines.append("  VERDICT: below its own geometry. This is a losing system.")
    elif lower <= mech:
        need = trades_to_detect(observed_win_rate, mech)
        lines.append(f"  VERDICT: not distinguishable from geometry yet. "
                     f"Needs ~{need:,.0f} trades.")
    else:
        lines.append("  VERDICT: clears its geometry at 90% confidence.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Edge over holding — the benchmark this module was missing.
#
# Everything above compares a setup against its own geometry, which catches a
# win rate bought with a tight target. It does not catch the other failure,
# and that one turned out to be live in this system.
#
# The validated deep-oversold setup, measured on 9,246 real occurrences:
#
#     wins more often      54.3%    vs   51.1% for any random session
#     average win         +4.47%    vs   +2.97%
#     average loss        -4.12%    vs   -1.79%
#     payoff ratio          1.08    vs     1.66
#     expectancy (1d)    +0.599%    vs  +0.659%
#     expectancy (10d)   +0.759%    vs  +1.682%
#
# Right more often, and worse at every horizon. It fires in violent
# conditions where a loss costs nearly what a win pays, while ordinary
# sessions pay 1.66 to 1. A hit-rate test applauds exactly this, and so does
# a skill-edge test, because neither asks "compared to not trading".
#
# Doing nothing is the real alternative and over a rising decade it is a high
# bar. Positive expectancy is not an edge. Positive expectancy ABOVE what the
# same capital earned unconditionally is.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldComparison:
    """A setup measured against simply holding over the same window."""

    n: int
    setup_expectancy_pct: float
    hold_expectancy_pct: float
    avg_win_pct: float
    avg_loss_pct: float

    @property
    def edge_pct(self) -> float:
        return self.setup_expectancy_pct - self.hold_expectancy_pct

    @property
    def payoff_ratio(self) -> float:
        """Average win over average loss. Below ~1.2, a high win rate is a
        warning rather than a result — something is being risked to buy it."""
        return abs(self.avg_win_pct / self.avg_loss_pct) if self.avg_loss_pct else 0.0

    @property
    def beats_holding(self) -> bool:
        return (self.n >= 200 and self.edge_pct > 0.0
                and self.payoff_ratio >= 1.2)

    def verdict(self) -> str:
        if self.n < 200:
            return (f"Only {self.n} trades — a run of luck is "
                    "indistinguishable from an edge at this size.")
        if self.edge_pct <= 0:
            return (f"Makes {self.setup_expectancy_pct:+.2f}% a trade, but "
                    f"holding made {self.hold_expectancy_pct:+.2f}% over the "
                    f"same window. That is {abs(self.edge_pct):.2f}% a trade "
                    "WORSE than doing nothing — being right more often does "
                    "not help when the losses are bigger.")
        if self.payoff_ratio < 1.2:
            return (f"Beats holding by {self.edge_pct:+.2f}% a trade, but "
                    f"wins pay only {self.payoff_ratio:.2f}x what losses "
                    "cost. Thin enough that a slightly worse run erases it.")
        return (f"Makes {self.setup_expectancy_pct:+.2f}% a trade against "
                f"{self.hold_expectancy_pct:+.2f}% for holding, "
                f"{self.edge_pct:+.2f}% better, wins paying "
                f"{self.payoff_ratio:.2f}x losses, over {self.n:,} trades.")


def compare_to_holding(setup_returns, hold_returns) -> HoldComparison:
    """Measure a setup against the same capital left alone.

    Both arguments are fractional returns (0.02 = 2%). `hold_returns` should
    be the unconditional series over the same period, not a filtered one — the
    point is to answer "was trading this better than not trading".
    """
    setup_returns = list(setup_returns)
    hold_returns = list(hold_returns)
    if not setup_returns:
        return HoldComparison(0, 0.0, 0.0, 0.0, 0.0)

    wins = [r for r in setup_returns if r > 0]
    losses = [r for r in setup_returns if r < 0]
    return HoldComparison(
        n=len(setup_returns),
        setup_expectancy_pct=sum(setup_returns) / len(setup_returns) * 100.0,
        hold_expectancy_pct=(sum(hold_returns) / len(hold_returns) * 100.0
                             if hold_returns else 0.0),
        avg_win_pct=(sum(wins) / len(wins) * 100.0) if wins else 0.0,
        avg_loss_pct=(sum(losses) / len(losses) * 100.0) if losses else 0.0,
    )
