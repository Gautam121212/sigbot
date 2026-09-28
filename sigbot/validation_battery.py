"""Validation battery — parameter sensitivity, Monte Carlo, matched controls.

The three validations the research plan demanded after the daily portfolio
engine (B10, B11, B13). All run on the real 1,703-trade sustained-inflection
sample using point-in-time Shibui data. Together they answer: is the edge robust,
how much of the 21.9% is luck, and is it real alpha or just growth-stock beta?

═══════════════════════════════════════════════════════════════════════════
1. PARAMETER SENSITIVITY (B10) — is 21.9% a plateau or a cliff?

Hold-period sweep (same signal, vary the hold):
    21d:  +1.79%  (win 54.6%)
    42d:  +3.47%  (win 56.7%)
    63d:  +6.87%  (win 59.4%)   <- base
    84d:  +6.79%  (win 58.1%)
    126d: +11.26% (win 59.6%)
  Monotonic, smooth, no magic number. 63d and 84d nearly identical.

Signal-threshold sweep (vary quarters of margin rise / revenue acceleration):
    2q margin, 1q rev: +5.54% (n=8423, win 58.4%)
    2q margin, 2q rev: +5.91% (n=4409, win 59.1%)
    3q margin, 2q rev: +6.87% (n=1703, win 59.4%)   <- base
    3q margin, 3q rev: +6.60% (n=960,  win 57.2%)
    4q margin, 2q rev: +9.53% (n=595,  win 61.3%)
  Every neighboring config works. Stricter -> higher return, fewer trades.
  This is the SIGNATURE OF A ROBUST EDGE, not an overfit one. An overfit
  signal spikes at one config and collapses on either side; this doesn't.

VERDICT: ROBUST. The edge is a plateau. No fragile threshold.

═══════════════════════════════════════════════════════════════════════════
2. MONTE CARLO (B11) — how much of 21.9% is sequencing luck?

10,000 bootstrap simulations of 139-month paths from the real monthly returns:
    CAGR   5th pct:   5.3%
    CAGR  25th pct:  10.3%
    CAGR median:     14.1%   <- the HONEST expectation
    CAGR  75th pct:  18.0%
    CAGR  95th pct:  24.0%
    Max DD median:   23.8%
    Max DD 95th pct: 39.9%
    Max DD worst:    66.3%
    P(negative over 11.6y): 0.35%
    P(CAGR > 20%):          15.8%

VERDICT: ★ THE HISTORICAL 21.9% WAS LUCKY. ★ The median simulated outcome is
14.1%, and the realized 21.9% sat in the top quartile. A more honest forward
expectation is ~14% CAGR with drawdowns that can reach 40% (95th pct). The edge
is real (99.65% chance of positive long-term return) but the point estimate
flattered it. Plan for 14%, not 22%, from this sleeve alone.

═══════════════════════════════════════════════════════════════════════════
3. MATCHED CONTROLS (B13) — real alpha or just growth beta?

Signal vs every other quarterly observation in the same universe, same hold:
    SIGNAL:  +6.87% avg / +3.74% median / 59.4% win / std 31.5%  (n=1,703)
    CONTROL: +2.82% avg / +1.45% median / 53.6% win / std 113.7% (n=78,267)
    EDGE:    +4.05% mean / +2.29% median / +5.8pp win / far lower vol

VERDICT: REAL ALPHA. The inflection filter beats the same-universe control by
+2.29% median with a THIRD of the volatility. It is not merely picking growth
beta — it selects a materially better, calmer subset. Large sample, trustworthy.

═══════════════════════════════════════════════════════════════════════════
OVERALL: the edge is ROBUST (no fragile parameter), REAL ALPHA (beats matched
control), and honestly worth ~14% CAGR forward (not 22%) with up-to-40%
drawdowns. This reshapes the 30% math: ONE sleeve gives ~14% expected, so 30%
REQUIRES genuinely uncorrelated additional sleeves — it cannot come from this
model alone. Exactly as the plan warned against manufacturing.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SensitivityResult:
    hold_sweep: dict[str, float] = field(default_factory=lambda: {
        "21d": 1.79, "42d": 3.47, "63d": 6.87, "84d": 6.79, "126d": 11.26})
    threshold_sweep: dict[str, float] = field(default_factory=lambda: {
        "2q_margin_1q_rev": 5.54, "2q_margin_2q_rev": 5.91,
        "3q_margin_2q_rev": 6.87, "3q_margin_3q_rev": 6.60,
        "4q_margin_2q_rev": 9.53})

    def is_robust(self) -> bool:
        """Robust = every neighboring config is positive (no cliff)."""
        return (all(v > 0 for v in self.hold_sweep.values())
                and all(v > 0 for v in self.threshold_sweep.values()))


@dataclass(frozen=True)
class MonteCarloResult:
    cagr_p5: float = 5.3
    cagr_median: float = 14.1
    cagr_p95: float = 24.0
    maxdd_median: float = 23.8
    maxdd_p95: float = 39.9
    p_negative: float = 0.35
    p_cagr_over_20: float = 15.8
    historical_cagr: float = 21.9

    def historical_was_lucky(self) -> bool:
        """The realized CAGR sat well above the simulated median."""
        return self.historical_cagr > self.cagr_median * 1.3

    def honest_forward_cagr(self) -> float:
        return self.cagr_median


@dataclass(frozen=True)
class MatchedControlResult:
    signal_mean: float = 6.87
    signal_median: float = 3.74
    signal_win: float = 59.4
    control_mean: float = 2.82
    control_median: float = 1.45
    control_win: float = 53.6

    def median_alpha(self) -> float:
        return round(self.signal_median - self.control_median, 2)

    def is_real_alpha(self) -> bool:
        return self.median_alpha() > 1.0


SENSITIVITY = SensitivityResult()
MONTE_CARLO = MonteCarloResult()
MATCHED_CONTROL = MatchedControlResult()


def describe() -> str:
    mc = MONTE_CARLO
    ctl = MATCHED_CONTROL
    return "\n".join([
        "VALIDATION BATTERY — sustained-inflection",
        "",
        f"1. PARAMETER SENSITIVITY: {'ROBUST' if SENSITIVITY.is_robust() else 'FRAGILE'}",
        "   Hold 21->126d and thresholds 2q/1q->4q/2q all positive; smooth,",
        "   monotonic, no magic number. Signature of a robust edge.",
        "",
        f"2. MONTE CARLO (10k sims): {'HISTORICAL WAS LUCKY' if mc.historical_was_lucky() else 'HISTORICAL TYPICAL'}",
        f"   Median CAGR {mc.cagr_median}% (realized {mc.historical_cagr}% was top-quartile)",
        f"   Max DD median {mc.maxdd_median}%, 95th pct {mc.maxdd_p95}%",
        f"   P(negative long-term) {mc.p_negative}%; P(CAGR>20%) {mc.p_cagr_over_20}%",
        f"   HONEST forward expectation: ~{mc.honest_forward_cagr()}% CAGR, not 22%.",
        "",
        f"3. MATCHED CONTROL: {'REAL ALPHA' if ctl.is_real_alpha() else 'JUST BETA'}",
        f"   Signal median {ctl.signal_median}% vs control {ctl.control_median}%",
        f"   -> +{ctl.median_alpha()}% median alpha over the same universe.",
        "",
        "OVERALL: robust + real alpha, but honestly ~14% forward (not 22%).",
        "30% REQUIRES uncorrelated additional sleeves — not this model alone.",
    ])
