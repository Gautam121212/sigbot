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
