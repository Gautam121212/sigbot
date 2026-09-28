"""The benchmark page — daily, monthly, yearly targets and whether they were met.

Three rows, each resetting on its own clock:
  * DAILY   — did the paper account beat its daily benchmark today? Resets daily.
  * MONTHLY — did it beat the monthly benchmark this month? Resets monthly.
  * YEARLY  — did it beat the yearly benchmark this year? Resets yearly.

The benchmark is the index return over the same window (the thing the account
has to beat to be worth running). Each row shows the target, the actual, and a
met/not-met check. "Reset" means the row measures only the CURRENT day / month
/ year — last period's result has rolled off, exactly like a real scorecard.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# Benchmark = the professional "exceptional" target (~20%/yr), the concentrated
# per-model goal, NOT the S&P (~12%). This is what a model must clear to be worth
# running per the professional-concentration analysis. Updated from the historical
# per-model run: the strong models target 20%, so the book benchmark is 20%/yr.
TARGET_YEARLY = 0.20                       # the exceptional professional bar
INDEX_MONTHLY = (1 + TARGET_YEARLY) ** (1 / 12) - 1   # ~1.53%/mo
INDEX_DAILY = (1 + TARGET_YEARLY) ** (1 / 252) - 1    # ~0.072%/day
INDEX_YEARLY = TARGET_YEARLY


@dataclass(frozen=True)
class BenchRow:
    period: str            # "Today", "This month", "This year"
    target_pct: float      # what the account must beat, in %
    actual_pct: float      # what it actually returned, in %
    met: bool
    detail: str


def _period_return(days: list[dict], start: datetime, now: datetime) -> float:
    """Compound the paper account's daily % over [start, now]."""
    growth = 1.0
    for d in days:
        try:
            dt = datetime.fromisoformat(d.get("date", "") + "T00:00:00+00:00")
        except ValueError:
            continue
        if start <= dt <= now:
            growth *= 1 + (d.get("pct", 0.0) or 0.0) / 100.0
    return (growth - 1) * 100.0


def benchmark_rows(paper: dict, when: datetime | None = None) -> list[BenchRow]:
    """The three benchmark rows for the current day, month, and year."""
    now = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    days = paper.get("days", []) or []

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    year_start = day_start.replace(month=1, day=1)

    rows = []
    for period, start, target in (
        ("Today", day_start, INDEX_DAILY * 100),
        ("This month", month_start, INDEX_MONTHLY * 100),
        ("This year", year_start, INDEX_YEARLY * 100),
    ):
        actual = _period_return(days, start, now)
        met = actual >= target
        rows.append(BenchRow(
            period=period, target_pct=round(target, 2), actual_pct=round(actual, 2),
            met=met,
            detail=(f"{actual:+.2f}% vs a {target:+.2f}% target — "
                    + ("met" if met else "not met"))))
    return rows
