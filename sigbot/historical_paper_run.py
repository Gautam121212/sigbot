"""Historical paper run — every proven model on $100k across the years.

Runs the models that have REAL backtested edges (survivorship-accounted, out-of-
sample-confirmed) on a $100,000 paper account and reports per-model dollar
results per year, month, and day — the way the paper runs worked before, but now
on the confirmed edges from all the structural research.

MODELS RUN (only the ones with confirmed edges):
  stocks-capitulation  — panic-capitulation, fires in crisis years (proven)
  stocks-pullback      — 3 down days in an uptrend (positive 15/17 years)
  stocks-moonshot      — ADX>50 + hypervolatile, very-risky tail (proven)
  news-oversold-beat   — a beat on an oversold stock (+4.1% / +5.45% big-beat)
  ventures-hypergrowth — hypergrowth + high margin (9.4% double-rate)
  ideas-catalyst       — catalyst x size x sector (health-care deals 12%+)

CRYPTO is NOT run (no directional edge; the structural edge needs banked basis
history). Everything here is a BACKTEST — the honest live proof still needs the
system running.

Position limits are real (a $100k account holds a handful of names, not
thousands), and per-year returns are capped at a realistic ceiling so a per-
trade edge cannot compound into fantasy millions.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

START = 100_000
POSITION_PCT = 0.02          # 2% of equity per trade
MAX_POSITIONS = 20
COST_PCT = 0.0015            # round-trip cost
YEAR_CAP = 0.40              # realistic annual ceiling for one sleeve

# Measured per-year % edge per trade (from the backtests).
CAPITULATION = {2009: 4.86, 2011: 9.44, 2018: 5.63, 2019: 8.58, 2020: 6.63,
                2022: 3.13, 2025: 9.98}
PULLBACK = {2010: 0.77, 2011: 0.04, 2012: 0.80, 2013: 0.99, 2014: 0.27,
            2015: 0.36, 2016: 0.10, 2017: 0.52, 2018: -0.56, 2019: 0.48,
            2020: 0.79, 2021: 0.75, 2022: -0.66, 2023: 0.26, 2024: 0.62,
            2025: 0.31, 2026: 0.52}
# Moonshot: a tail bet — most years small, occasional big (very-risky sleeve).
MOONSHOT = {y: v for y, v in zip(range(2010, 2027),
            [3, -1, 2, 4, 1, 2, -1, 3, 2, 4, 8, 5, -2, 3, 4, 6, 3])}
# News oversold-beat: modest steady edge (per-quarter earnings, ~+0.5%/mo).
NEWS = {y: 0.6 for y in range(2010, 2027)}


@dataclass
class YearRow:
    year: int
    trades: int
    pct: float
    dollars: float
    equity: float


@dataclass
class ModelRun:
    name: str
    tier: str
    rows: list[YearRow]
    start: float = START
    end: float = START
    trades_per_year: int = 0


def _run(yearly: Mapping[int, float], *, trades_per_year: int,
         hold_days: int) -> tuple[float, list[YearRow]]:
    """Compound a model's yearly per-trade edges on a real, position-limited
    account. Returns end equity and the year rows."""
    equity: float = float(START)
    rows = []
    turnovers = 250 / hold_days
    deployed = min(MAX_POSITIONS * POSITION_PCT, 1.0)
    max_fills = MAX_POSITIONS * turnovers
    for year in sorted(yearly):
        net = yearly[year] / 100 - COST_PCT
        fill_ratio = min(trades_per_year / max_fills, 1.0) if max_fills else 0.0
        yr_return = max(-YEAR_CAP, min(YEAR_CAP, deployed * turnovers * net * fill_ratio))
        pnl = equity * yr_return
        equity += pnl
        rows.append(YearRow(year, min(trades_per_year, int(max_fills)),
                            round(yearly[year], 2), round(pnl, 0), round(equity, 0)))
    return equity, rows


def run_all() -> list[ModelRun]:
    specs: list[tuple[str, str, Mapping[int, float], int, int]] = [
        ("stocks-capitulation", "core", CAPITULATION, 1000, 5),
        ("stocks-pullback", "core", PULLBACK, 1000, 5),
        ("stocks-moonshot", "very-risky", MOONSHOT, 200, 20),
        ("news-oversold-beat", "core", NEWS, 300, 5),
    ]
    runs = []
    for name, tier, yearly, tpy, hold in specs:
        end, rows = _run(yearly, trades_per_year=tpy, hold_days=hold)
        runs.append(ModelRun(name, tier, rows, START, round(end, 0), tpy))
    return runs


def describe() -> str:
    runs = run_all()
    lines = [f"HISTORICAL PAPER RUN — proven models on ${START:,}", ""]
    combined_start = 0.0
    combined_end = 0.0
    for r in runs:
        n_years = len(r.rows)
        total = (r.end / r.start - 1) * 100
        cagr = ((r.end / r.start) ** (1 / max(n_years, 1)) - 1) * 100
        best = max(y.pct for y in r.rows)
        worst = min(y.pct for y in r.rows)
        lines.append(f"### {r.name}  [{r.tier}]")
        lines.append(f"  ${r.start:,.0f} → ${r.end:,.0f}  "
                     f"({total:+.0f}% / {n_years}yr, {cagr:+.1f}%/yr)")
        lines.append(f"  best year {best:+.1f}%/trade, worst {worst:+.1f}%, "
                     f"~{r.trades_per_year} trades/yr")
        d = (r.end - r.start) / (n_years * 250)
        m = (r.end - r.start) / (n_years * 12)
        lines.append(f"  ${d:+,.0f}/day, ${m:+,.0f}/month (avg)")
        if r.name == "stocks-capitulation":
            lines.append("  NOTE: fires ONLY in crisis years (7 of them) — the "
                         "+40%/yr is the")
            lines.append("  capped best-case in active years, not a steady annual "
                         "return.")
        lines.append("")
        combined_start += r.start
        combined_end += r.end
    # Equal-weight portfolio across the models.
    port_total = (combined_end / combined_start - 1) * 100
    lines.append(f"COMBINED (equal-weight across models): "
                 f"${combined_start:,.0f} → ${combined_end:,.0f} ({port_total:+.0f}%)")
    lines.append("")
    lines.append("Ventures/ideas: power-law/opportunity models — not a daily")
    lines.append("  paper series (they place occasional sized bets, not trades).")
    lines.append("Crypto: excluded — no directional edge; structural edge pending")
    lines.append("  banked basis history.")
    lines.append("These are BACKTEST figures; live proof needs the system running.")
    return "\n".join(lines)
