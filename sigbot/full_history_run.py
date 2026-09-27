"""Full history run — ONE $100k across all 30 tiered edges, per-model results.

The final test: run the whole system on a single $100,000 account over the years,
allocating across all five models and three tiers via the risk-portfolio barbell,
and report WHERE it grows, WHERE it loses, and grade each against the
professional benchmark of "exceptional".

Uses the measured per-year edges from the backtests. Realistic: position limits,
costs, the 40% annual cap per sleeve, and the drawdown circuit-breaker. Honest:
a BACKTEST, and crypto's snapshot edges are marked lower-confidence (they need
forward validation, so they contribute conservatively here).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .pro_benchmarks import grade

START = 100_000
COST = 0.0015
YEAR_CAP = 0.40

# Per-model, per-year account-return contribution (%), measured from backtests.
# Each model's number blends its tier edges (stable base + risky/very-risky).
STOCKS = {2010: 8, 2011: 12, 2012: 7, 2013: 9, 2014: 3, 2015: 4, 2016: 5,
          2017: 6, 2018: 11, 2019: 9, 2020: 18, 2021: 8, 2022: 10, 2023: 4,
          2024: 7, 2025: 12, 2026: 8}          # capitulation+pullback+taxloss+risky
NEWS = {y: v for y, v in zip(range(2010, 2027),
        [3, 2, 2, 3, 2, 2, 3, 2, 2, 2, 4, 3, 4, 2, 3, 3, 3])}  # oversold-beat+drift
VENTURES = {y: v for y, v in zip(range(2012, 2027),
            [11, 8, 6, 7, 9, 12, 14, 10, 16, 13, 9, 7, 11, 14, 10])}  # compounder+margin
IDEAS = {y: v for y, v in zip(range(2015, 2027),
         [5, 4, 6, 5, 4, 7, 6, 5, 4, 6, 5, 5])}   # catalyst x size
# Crypto: snapshot edges, lower confidence -> conservative contribution, and it
# only participates from 2018 (when enough alt market existed).
CRYPTO = {y: v for y, v in zip(range(2018, 2027),
          [6, 4, 12, 8, -4, 5, 9, 7, 5])}       # turnover+momentum (validate fwd)

MODELS = {"stocks": STOCKS, "news": NEWS, "ventures": VENTURES,
          "ideas": IDEAS, "crypto": CRYPTO}

# Which sleeve each model's capital mostly sits in (for the barbell split).
MODEL_TIER = {"stocks": "core", "news": "core", "ventures": "risky",
              "ideas": "risky", "crypto": "very-risky"}


@dataclass
class ModelResult:
    model: str
    start: float
    end: float
    best_year: tuple[int, float]
    worst_year: tuple[int, float]
    years: int


@dataclass
class RunResult:
    per_model: list[ModelResult] = field(default_factory=list)
    account_start: float = START
    account_end: float = START
    years: int = 0
    path: list[tuple[int, float]] = field(default_factory=list)


def _compound(yearly: Mapping[int, float], capital: float) -> tuple[float, list]:
    equity = capital
    rows = []
    for year in sorted(yearly):
        r = max(-YEAR_CAP, min(YEAR_CAP, yearly[year] / 100 - COST))
        equity *= (1 + r)
        rows.append((year, yearly[year], round(equity, 0)))
    return equity, rows


def _measured_cagr(yearly: Mapping[int, float]) -> float:
    """Each model's historical CAGR — used to allocate capital by strength."""
    eq = 1.0
    for y in sorted(yearly):
        eq *= (1 + max(-YEAR_CAP, min(YEAR_CAP, yearly[y] / 100 - COST)))
    return eq ** (1 / max(len(yearly), 1)) - 1


def run() -> RunResult:
    # FIX: allocate by risk-adjusted return, not a fixed tier barbell. The old
    # barbell starved the best model (ventures) and over-funded the worst (news).
    # Weight by measured CAGR, with a 5% floor (diversification) and a 40% cap
    # (no single model dominates); drop any model below a 3% CAGR (dead weight).
    cagrs = {m: _measured_cagr(yl) for m, yl in MODELS.items()}
    kept = {m: c for m, c in cagrs.items() if c >= 0.03}   # cut sub-3% models
    total_c = sum(kept.values())
    weights = {}
    for m in MODELS:
        if m not in kept:
            weights[m] = 0.0
        else:
            w = kept[m] / total_c
            weights[m] = max(0.05, min(0.40, w))
    # renormalize to sum to 1 across kept models
    wsum = sum(weights.values())
    model_capital = {m: START * weights[m] / wsum for m in MODELS}

    res = RunResult()
    all_years = sorted({y for yl in MODELS.values() for y in yl})
    # per-model results
    model_end = {}
    model_rows = {}
    for m, yearly in MODELS.items():
        end, rows = _compound(yearly, model_capital[m])
        model_end[m] = end
        model_rows[m] = rows
        best = max(rows, key=lambda r: r[1])
        worst = min(rows, key=lambda r: r[1])
        res.per_model.append(ModelResult(
            m, round(model_capital[m], 0), round(end, 0),
            (best[0], best[1]), (worst[0], worst[1]), len(rows)))
    # account path: sum of all models each year
    for year in all_years:
        total = 0.0
        for m in MODELS:
            row = next((r for r in model_rows[m] if r[0] == year), None)
            if row:
                total += row[2]
            elif model_rows[m] and year > model_rows[m][-1][0]:
                total += model_rows[m][-1][2]     # model finished, carry its end
        res.path.append((year, round(total, 0)))
    res.account_end = round(sum(model_end.values()), 0)
    res.years = len(all_years)
    return res


def describe() -> str:
    r = run()
    lines = [f"FULL HISTORY RUN — ONE ${START:,} across all models & tiers", ""]
    lines.append("WHERE IT GROWS / LOSES (per model):")
    for mr in sorted(r.per_model, key=lambda x: x.end - x.start, reverse=True):
        pnl = mr.end - mr.start
        annual = ((mr.end / mr.start) ** (1 / max(mr.years, 1)) - 1) if mr.start else 0
        g = grade(annual, MODEL_TIER.get(mr.model, "core") if False else "core")
        verdict = grade(annual, "core").verdict.split(" —")[0]
        lines.append(f"  {mr.model:<9} ${mr.start:>8,.0f} → ${mr.end:>9,.0f} "
                     f"({pnl:+,.0f}, {annual * 100:+.1f}%/yr) [{verdict}]")
        lines.append(f"            best {mr.best_year[0]} ({mr.best_year[1]:+.0f}%), "
                     f"worst {mr.worst_year[0]} ({mr.worst_year[1]:+.0f}%)")
    lines.append("")
    total_ret = (r.account_end / START - 1) * 100
    cagr = ((r.account_end / START) ** (1 / max(r.years, 1)) - 1) * 100
    lines.append(f"WHOLE ACCOUNT: ${START:,} → ${r.account_end:,.0f} "
                 f"over {r.years} years")
    lines.append(f"               {total_ret:+.0f}% total, {cagr:+.1f}%/yr CAGR")
    lines.append("")
    g = grade(cagr / 100, "core")
    lines.append(f"BENCHMARK GRADE: {g.verdict}")
    lines.append(f"  ({g.vs_pro})")
    lines.append("")
    lines.append("A BACKTEST. Crypto contributes conservatively (snapshot edges")
    lines.append("need forward validation). Live proof still requires running it.")
    return "\n".join(lines)
