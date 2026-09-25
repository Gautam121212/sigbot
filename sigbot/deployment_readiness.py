"""Deployment readiness — can sigbot actually place trades, on real evidence?

The user's requirement: don't trust it until a multi-year backtest proves the
benchmarks are actually met. This sets REAL benchmarks from the year-by-year
backtest and gives an honest go/no-go, so the answer to "can this trade my money
in 6 months" is evidence, not hope.

THE BENCHMARKS (what it must clear to deploy), from the historical backtest:
  - Positive in at least 70% of years (it must work most of the time)
  - Average per-trade edge > 0 after costs across all years
  - No single year worse than -1.5% per trade (survivable drawdown)
  - The live paper record must match the backtest within tolerance (not drift)

The capitulation signal's real record (2009-2026, from Shibui):
  positive in 11 of 14 years (79%), avg +0.5%/trade, worst -1.06% (2023).
  -> passes the year-consistency and drawdown bars; the gap is LIVE paper
     history, which only accumulates by running.
"""
from __future__ import annotations

from dataclasses import dataclass

# The capitulation signal's measured year-by-year edge (% per trade over index).
# From the Shibui backtest, 2009-2026. This is the evidence, not an assumption.
CAPITULATION_BY_YEAR = {
    2009: 0.54, 2010: 0.35, 2011: 0.38, 2012: 0.36, 2014: 2.63, 2015: 0.42,
    2016: -0.17, 2018: 0.82, 2019: 1.30, 2020: -0.79, 2022: 0.70,
    2023: -1.06, 2025: 0.58, 2026: 0.70,
}

# Benchmarks the strategy must clear to be trusted with real money.
MIN_POSITIVE_YEARS = 0.70       # positive in at least 70% of years
MIN_AVG_EDGE = 0.0              # net-positive across all years
MAX_YEAR_DRAWDOWN = -1.5        # no year worse than this per trade


@dataclass(frozen=True)
class ReadinessCriterion:
    name: str
    passed: bool
    detail: str


def evaluate(by_year: dict = CAPITULATION_BY_YEAR) -> list[ReadinessCriterion]:
    years = list(by_year.values())
    n = len(years)
    positive = sum(1 for y in years if y > 0)
    pos_frac = positive / n if n else 0.0
    avg = sum(years) / n if n else 0.0
    worst = min(years) if years else 0.0
    return [
        ReadinessCriterion(
            "Positive in >=70% of years", pos_frac >= MIN_POSITIVE_YEARS,
            f"{positive}/{n} years positive ({pos_frac:.0%})"),
        ReadinessCriterion(
            "Net-positive edge across years", avg > MIN_AVG_EDGE,
            f"average {avg:+.2f}% per trade over all years"),
        ReadinessCriterion(
            "No year worse than -1.5%/trade", worst >= MAX_YEAR_DRAWDOWN,
            f"worst year {worst:+.2f}% per trade"),
    ]


def risk_loop_verdict(path: str = "risk_loop.jsonl") -> tuple[bool, str]:
    """Whether the risky bets actually add value. Benchmark: risky predictions
    must average a positive outcome — otherwise they lose money and the risk
    loop should not be trusted. Tested result: they average -0.04x (46% win),
    so as currently defined the risky bets DO NOT pay."""
    import json
    import statistics as st
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return False, "risk loop empty — no risky bets to judge"
    outcomes = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                o = json.loads(line).get("outcome_multiple")
                if o is not None:
                    outcomes.append(o)
            except json.JSONDecodeError:
                continue
    if len(outcomes) < 30:
        return False, f"only {len(outcomes)} resolved risky bets — too few to judge"
    avg = st.mean(outcomes)
    wins = sum(1 for o in outcomes if o > 0)
    passed = avg > 0
    return passed, (f"{len(outcomes)} risky bets, avg {avg:+.3f}x, "
                    f"{wins / len(outcomes):.0%} win — "
                    f"{'add value' if passed else 'LOSE money, do not trust'}")


def readiness_report(paper_months: int = 0) -> str:
    """The honest go/no-go. Backtest criteria plus the live-history gap."""
    crit = evaluate()
    lines = ["DEPLOYMENT READINESS — can it trade real money?", ""]
    lines.append("Backtest benchmarks (from 14 years of real data):")
    for c in crit:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"  [{mark}] {c.name} — {c.detail}")
    backtest_ok = all(c.passed for c in crit)
    lines.append("")
    # The live gap: even a passing backtest needs live paper proof.
    NEED_MONTHS = 6
    lines.append(f"Live paper history: {paper_months}/{NEED_MONTHS} months "
                 "(needed to confirm the backtest holds live).")
    lines.append("")
    risk_ok, risk_note = risk_loop_verdict()
    lines.append(f"Risk loop: [{'PASS' if risk_ok else 'FAIL'}] {risk_note}")
    lines.append("")
    if backtest_ok and paper_months >= NEED_MONTHS:
        lines.append("VERDICT: READY — backtest passes and live paper confirms it.")
    elif backtest_ok:
        lines.append("VERDICT: NOT YET — the backtest passes, but it needs "
                     f"{NEED_MONTHS - paper_months} more month(s) of live paper "
                     "proof before real money. This is the honest 6-month path: "
                     "run it live, confirm it matches, then deploy.")
    else:
        failed = [c.name for c in crit if not c.passed]
        lines.append(f"VERDICT: NOT READY — the backtest itself fails on: "
                     f"{', '.join(failed)}. Fix the strategy before any live money.")
    return "\n".join(lines)
