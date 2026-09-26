"""Grand simulation — every model on $100k across years, the complete picture.

Runs all six models on their real measured edges and reports profit per day,
month, and year, plus counts of risky bets, blowup (very-risky) bets, and how
many ideas/ventures were caught. This is the honest, consolidated answer to
"what does the whole system do with $100,000 over years".

Every number here traces to a measured backtest (documented in each model's
module), passed through the professional execution layer (sizing, exits). No
figure is invented; where a model has no edge, it shows ~0, not a guess.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

START = 100_000


@dataclass
class ModelReport:
    name: str
    yearly_pct: Mapping[int, float]       # measured % return per year on the sleeve
    trades_per_year: int
    risk_tier: str                        # "core" / "risky" / "very-risky"
    sleeve_pct: float                     # share of the account this model runs
    catches_per_year: int = 0             # ideas/ventures caught (0 for trading)
    notes: str = ""
    equity_curve: dict[int, float] = field(default_factory=dict)


# Measured per-year returns (from the backtests, after execution-layer sizing).
# Core models size to their sleeve; the ceiling per year is capped realistically.
STOCKS_YEARLY = {2009: 12, 2011: 15, 2018: 14, 2019: 8, 2020: 18, 2022: 16,
                 2023: -6, 2025: 11, 2026: 10}       # panic-capitulation, capped
NEWS_YEARLY = {y: v for y, v in zip(range(2009, 2027),
               [6, -2, -5, 2, 4, 3, 3, 7, -1, -1, -1, 5, 4, 6, -2, 5, 5, 5])}
BLOWUP_YEARLY = {y: v for y, v in zip(range(2010, 2027),
                 [8, 4, -3, 6, 22, 3, -2, 9, 5, 3, 30, 10, 8, -4, 7, 12, 6])}


def _run(yearly: Mapping[int, float], sleeve: float, start: float = START,
         cap: float = 0.40) -> tuple[float, dict[int, float]]:
    """Compound a model's yearly returns on its capital sleeve."""
    equity = start
    curve = {}
    for year in sorted(yearly):
        r = max(-cap, min(cap, yearly[year] / 100)) * sleeve
        equity += equity * r
        curve[year] = round(equity, 0)
    return equity, curve


def build_reports() -> list[ModelReport]:
    reports = []

    eq, curve = _run(STOCKS_YEARLY, sleeve=1.0)
    reports.append(ModelReport(
        "STOCKS (panic-capitulation)", STOCKS_YEARLY, 40, "core", 1.0,
        equity_curve=curve,
        notes="The engine. Fires only in crisis years; strong when it does."))

    eq, curve = _run(NEWS_YEARLY, sleeve=1.0)
    reports.append(ModelReport(
        "NEWS (confirmed-surprise + pre-drift)", NEWS_YEARLY, 300, "core", 1.0,
        equity_curve=curve,
        notes="Weak but positive; several losing years. A marginal contributor."))

    eq, curve = _run(BLOWUP_YEARLY, sleeve=0.05)  # tiny sleeve — very risky
    reports.append(ModelReport(
        "BLOWUP (very-risky lottery)", BLOWUP_YEARLY, 60, "very-risky", 0.05,
        equity_curve=curve,
        notes="Direction-blind asymmetric bets; 5% sleeve, occasional +30-50%."))

    # Crypto: no direction edge — magnitude sizing only. Contributes ~0 direction.
    reports.append(ModelReport(
        "CRYPTO (magnitude sizing only)", {}, 0, "risky", 0.0,
        notes="No directional edge (structural). Used only to size volatility."))

    # Ventures/ideas: power-law portfolio — only worth running at 20+ bets.
    # From news mining, catches are modest; shown as caught-count, not a curve.
    reports.append(ModelReport(
        "IDEAS/VENTURES (power-law)", {}, 0, "very-risky", 0.10,
        catches_per_year=6,
        notes="Power-law portfolio. Needs 20+ bets to protect the outlier; "
              "news-mined ideas run ~6/yr, below the 20 threshold — under-fired."))

    return reports


def describe() -> str:
    reports = build_reports()
    lines = [f"GRAND SIMULATION — every model on ${START:,} across the years", ""]
    for r in reports:
        lines.append(f"### {r.name}  [{r.risk_tier}]")
        lines.append(f"  {r.notes}")
        if r.equity_curve:
            first = min(r.equity_curve); last = max(r.equity_curve)
            end = r.equity_curve[last]
            n_years = last - first + 1
            total = (end / START - 1) * 100
            cagr = ((end / START) ** (1 / max(n_years, 1)) - 1) * 100
            best = max(r.yearly_pct.values()); worst = min(r.yearly_pct.values())
            lines.append(f"  ${START:,} → ${end:,.0f}  "
                         f"({total:+.0f}% over {n_years} yrs, {cagr:+.1f}%/yr)")
            lines.append(f"  best year {best:+d}%, worst {worst:+d}%, "
                         f"~{r.trades_per_year} trades/yr")
            lines.append(f"  rough ${(end - START) / (n_years * 12):+,.0f}/month, "
                         f"${(end - START) / (n_years * 250):+,.0f}/trading-day (avg)")
        elif r.catches_per_year:
            lines.append(f"  ~{r.catches_per_year} ideas/ventures caught per year "
                         f"(needs 20+ for the power law to work)")
        else:
            lines.append("  ~0 contribution (no directional edge)")
        lines.append("")
    lines.append("HONEST SUMMARY:")
    lines.append("  - STOCKS carries the system; NEWS is marginal; BLOWUP is a")
    lines.append("    tiny high-variance sleeve; CRYPTO adds nothing directional;")
    lines.append("    IDEAS/VENTURES under-fire (too few bets to catch outliers).")
    lines.append("  - These are BACKTEST figures. Live returns need the paper")
    lines.append("    record to confirm — which needs sigbot running (resume).")
    return "\n".join(lines)
