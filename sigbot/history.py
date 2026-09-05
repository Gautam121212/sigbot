"""History depth — which assets can answer a question about the past.

Your point, in your words: *"take into consideration those stocks specially
which have all historic data available, and after months of running and
learning add new stocks as it keeps growing."*

That is two things, and both are missing.

**Now.** The event store needs matching precedents before it says anything. At
roughly four earnings a year and two launches, that is one to three years of
history minimum, and more before the interval narrows to anything useful. An
asset listed in 2024 cannot produce a precedent count above zero for years, and
pointing the scanner at it burns slots a twenty-year name would fill. Nothing in
the system currently tells them apart.

**Later.** A shallow asset is not permanently disqualified. It is disqualified
*today*, and it becomes eligible on a date this module can calculate. That date
is the thing worth reporting: "RIVN qualifies in 14 months" is a plan, whereas
silently ignoring it forever is a decision nobody made.

## What counts as usable history

Not the span from first bar to last. Gaps, halts and stale stretches make a
frame look longer than the record it actually contains, so `usable_years()`
measures **bars actually present against bars that should be there**, and a
frame that is mostly holes is reported as the shorter thing it is.

## Why depth is not quality

A deep history means the asset *can* answer questions about its past. It says
nothing about whether the answers are useful — a twenty-year record of noise is
still noise. Depth gates which questions are worth asking; the Wilson bound
still decides what the answers are worth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

import numpy as np
import pandas as pd

BARS_PER_YEAR = {"1d": 252.0, "1h": 1638.0, "15m": 6552.0}
MIN_COVERAGE = 0.80          # below this, the frame is mostly holes


class Depth(str, Enum):
    DEEP = "DEEP"            # 10y+ — every question is answerable
    MEDIUM = "MEDIUM"        # 5-10y — precedent work is viable
    SHALLOW = "SHALLOW"      # 2-5y — price models only
    NEW = "NEW"              # under 2y — nothing historical

    @property
    def label(self) -> str:
        return {
            Depth.DEEP: "Deep history — precedent and pattern work",
            Depth.MEDIUM: "Enough history for precedent work",
            Depth.SHALLOW: "Price models only, too thin for precedents",
            Depth.NEW: "Too new for anything historical",
        }[self]

    @property
    def precedent_eligible(self) -> bool:
        return self in (Depth.DEEP, Depth.MEDIUM)


THRESHOLDS = ((10.0, Depth.DEEP), (5.0, Depth.MEDIUM), (2.0, Depth.SHALLOW))
PRECEDENT_MIN_YEARS = 5.0


@dataclass(frozen=True)
class History:
    symbol: str
    bars: int
    span_years: float        # first bar to last
    usable_years: float      # bars actually present, in years
    coverage: float          # usable / span
    depth: Depth
    first_bar: str
    last_bar: str
    gap_note: str = ""

    @property
    def precedent_eligible(self) -> bool:
        return self.depth.precedent_eligible and self.coverage >= MIN_COVERAGE

    def qualifies_in_months(self, target: float = PRECEDENT_MIN_YEARS) -> float | None:
        """Months until this asset has enough history, if it keeps trading.

        None once it already qualifies. The point of returning a number rather
        than a boolean is that a shallow asset is not rejected, it is early —
        and a date is a plan where silence is a decision nobody made.
        """
        if self.usable_years >= target:
            return None
        return round((target - self.usable_years) * 12.0, 1)

    def eligible_on(self, target: float = PRECEDENT_MIN_YEARS) -> date | None:
        months = self.qualifies_in_months(target)
        if months is None:
            return None
        try:
            last = date.fromisoformat(self.last_bar[:10])
        except ValueError:
            return None
        return last + timedelta(days=int(months * 30.44))

    def render(self) -> str:
        lines = [f"{self.symbol}: {self.depth.value} — {self.usable_years:.1f} years "
                 f"usable of {self.span_years:.1f} spanned "
                 f"({self.coverage:.0%} coverage)"]
        if self.gap_note:
            lines.append(f"  {self.gap_note}")
        if self.precedent_eligible:
            lines.append("  Eligible for precedent and pattern work.")
        else:
            when = self.eligible_on()
            lines.append(f"  Not eligible yet — {self.depth.label.lower()}."
                         + (f" Qualifies around {when.isoformat()} if it keeps "
                            "trading." if when else ""))
        return "\n".join(lines)


def measure(bars: pd.DataFrame, symbol: str = "?", interval: str = "1d") -> History:
    """How much history this frame actually contains."""
    if bars is None or bars.empty or "close" not in bars.columns:
        return History(symbol, 0, 0.0, 0.0, 0.0, Depth.NEW, "", "",
                       "no usable rows")

    idx = pd.DatetimeIndex(bars.index)
    n = len(bars)
    span_days = max((idx[-1] - idx[0]).days, 1)
    span_years = span_days / 365.25
    per_year = BARS_PER_YEAR.get(interval, 252.0)
    usable_years = n / per_year
    coverage = min(1.0, usable_years / span_years) if span_years > 0 else 0.0

    depth = Depth.NEW
    for floor, level in THRESHOLDS:
        if usable_years >= floor:
            depth = level
            break

    note = ""
    if coverage < MIN_COVERAGE:
        note = (f"only {n:,} bars across {span_years:.1f} years — "
                f"{1 - coverage:.0%} of the period is missing, so the record is "
                "shorter than the span suggests")
    else:
        gaps = np.diff(idx.values).astype("timedelta64[D]").astype(int)
        if gaps.size and interval == "1d":
            long_gaps = int((gaps > 10).sum())
            if long_gaps:
                note = f"{long_gaps} gap(s) longer than 10 days — halts or delisting"

    return History(symbol, n, round(span_years, 2), round(usable_years, 2),
                   round(coverage, 3), depth, str(idx[0].date()), str(idx[-1].date()),
                   note)


def rank(frames: dict[str, pd.DataFrame], interval: str = "1d") -> list[History]:
    """Every asset by usable history, deepest first."""
    return sorted((measure(b, s, interval) for s, b in frames.items()),
                  key=lambda h: -h.usable_years)


def precedent_universe(frames: dict[str, pd.DataFrame], limit: int | None = None,
                       interval: str = "1d") -> list[str]:
    """The assets worth pointing the event scanner at, today."""
    eligible = [h.symbol for h in rank(frames, interval) if h.precedent_eligible]
    return eligible[:limit] if limit else eligible


def growth_report(frames: dict[str, pd.DataFrame], interval: str = "1d") -> str:
    """What is eligible now, and what becomes eligible when."""
    ranked = rank(frames, interval)
    now = [h for h in ranked if h.precedent_eligible]
    soon = sorted((h for h in ranked if not h.precedent_eligible
                   and h.qualifies_in_months() is not None),
                  key=lambda h: h.qualifies_in_months() or 1e9)

    lines = [f"{len(now)} of {len(ranked)} assets have enough history for "
             "precedent work."]
    if now:
        lines.append("")
        lines.append("Eligible now (deepest first):")
        lines += [f"  {h.symbol:<14} {h.usable_years:>5.1f}y  {h.depth.value}"
                  for h in now[:12]]
    if soon:
        lines.append("")
        lines.append("Becomes eligible as it keeps trading:")
        for h in soon[:8]:
            months = h.qualifies_in_months()
            when = h.eligible_on()
            lines.append(f"  {h.symbol:<14} {h.usable_years:>5.1f}y  "
                         f"in ~{months:.0f} months"
                         + (f" ({when.isoformat()})" if when else ""))
    lines.append("")
    lines.append("Depth says which questions an asset can answer, not whether the "
                 "answers are worth anything. A twenty-year record of noise is "
                 "still noise.")
    return "\n".join(lines)
