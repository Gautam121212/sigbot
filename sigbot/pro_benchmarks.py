"""Professional return benchmarks — the yardstick for judging every model.

The gap the user caught: sigbot had no reference for what returns professionals
consider GOOD, EXCEPTIONAL, or WORTHLESS. Without it, "+5%/yr" is meaningless —
is that great or garbage? This encodes the real professional benchmarks (from
hedge-fund, quant, crypto-fund and VC data) at three risk tiers, so every model
can be GRADED against what the pros actually achieve.

THE BENCHMARKS (annual, from the research)
------------------------------------------
CORE / low-risk (market-neutral, systematic equity):
  hedge funds long-run ~10.7%/yr; quant funds 10-17%; "sweet spot" 10-20% at
  Sharpe 1.5-2. Sharpe 1.0 beats 95% of funds; 1.5+ is elite (Renaissance).
  Market-neutral low-vol: even 2-3%/yr is "very good" with tight drawdown.

RISKY / higher-vol (aggressive systematic, crypto quant):
  30-50%/yr achievable but with 30%+ volatility; crypto quant Sharpe ~1.5.
  The return must be paid for in drawdown — 30% return with 50% drawdown is
  still "objectively excellent" per the crypto-fund research.

VERY-RISKY / blowup (venture, moonshot):
  VC top-quartile 15-27% net IRR at the FUND level, but individual seed bets
  target 100x; 1-3 of 20-30 bets drive 50-80% of returns; 10-15 go to zero.
  Blowup range: -40% to +1,111%. Judged on the TAIL, not the average.
"""
from __future__ import annotations

from dataclasses import dataclass

# Annual return thresholds by tier: (worthless, decent, good, exceptional).
CORE = (0.0, 0.08, 0.15, 0.25)          # <0 bad, 8% decent, 15% good, 25%+ exceptional
RISKY = (0.0, 0.15, 0.30, 0.50)         # higher bar — must beat core to justify risk
# Ventures/VC portfolio: top-quartile IRR is 15-27%, so the portfolio bar is
# lower than a single moonshot. 8% decent, 15% good, 27% exceptional.
VERY_RISKY = (0.0, 0.08, 0.15, 0.27)

# Sharpe thresholds (risk-adjusted): 1.0 beats 95% of funds, 1.5 elite.
SHARPE_GOOD = 1.0
SHARPE_ELITE = 1.5


@dataclass(frozen=True)
class Grade:
    annual_pct: float
    tier: str
    verdict: str               # worthless / decent / good / exceptional
    vs_pro: str                # how it compares to the pro benchmark


def _thresholds(tier: str) -> tuple[float, float, float, float]:
    return {"core": CORE, "risky": RISKY, "very-risky": VERY_RISKY}.get(tier, CORE)


def grade(annual_return: float, tier: str = "core") -> Grade:
    """Grade an annual return against the professional benchmark for its tier."""
    bad, decent, good, exceptional = _thresholds(tier)
    pct = annual_return * 100 if abs(annual_return) < 5 else annual_return
    r = annual_return if abs(annual_return) < 5 else annual_return / 100
    if r < bad:
        verdict = "LOSING money — worse than cash"
    elif r < decent:
        verdict = "worthless — below the professional floor"
    elif r < good:
        verdict = "decent — a real but modest edge"
    elif r < exceptional:
        verdict = "GOOD — competitive with professional funds"
    else:
        verdict = "EXCEPTIONAL — top-tier professional territory"
    ref = {"core": "hedge funds ~11%/yr, quant 10-17%, sweet spot 15-25%",
           "risky": "aggressive quant 30-50%/yr with 30%+ volatility",
           "very-risky": "VC top-quartile 15-27% IRR; blowup tail 100%+"}[tier]
    return Grade(round(pct, 1), tier, verdict, f"pro benchmark: {ref}")


def daily_monthly_yearly(annual_return: float) -> tuple[float, float, float]:
    """Break an annual return into rough daily, monthly, yearly figures on $100k."""
    yearly = 100_000 * annual_return
    monthly = 100_000 * ((1 + annual_return) ** (1 / 12) - 1)
    daily = 100_000 * ((1 + annual_return) ** (1 / 252) - 1)
    return round(daily, 0), round(monthly, 0), round(yearly, 0)


def describe(model_returns: dict[str, tuple[float, str]]) -> str:
    """Grade each model. model_returns maps name -> (annual_return, tier)."""
    lines = ["MODEL GRADES vs PROFESSIONAL BENCHMARKS (on $100,000)", ""]
    for name, (ret, tier) in model_returns.items():
        g = grade(ret, tier)
        d, m, y = daily_monthly_yearly(ret)
        lines.append(f"### {name}  [{tier}]")
        lines.append(f"  {g.annual_pct:+.1f}%/yr → ${d:+,.0f}/day, ${m:+,.0f}/month, ${y:+,.0f}/year")
        lines.append(f"  {g.verdict}")
        lines.append(f"  ({g.vs_pro})")
        lines.append("")
    return "\n".join(lines)
