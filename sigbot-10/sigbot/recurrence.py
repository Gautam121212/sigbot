"""Recurrence measurement — how often has this actually happened before?

This module answers your points 2 and 3, and it does so by **counting, not
forecasting**. That distinction is why it can be trusted on day one instead of
after five months of collection.

"AVGO has followed an NVDA 2-sigma shock 47 times out of 112 over six years"
is a fact about the past. It carries a confidence interval you can compute
exactly, and no market efficiency argument can make it wrong. Contrast with
"AVGO will rise 2% tomorrow", which is a claim about the future that the market
has every incentive to have already priced.

What the frequency table does NOT tell you is that the rate will hold. Relations
decay as they become known. So every table here reports the rate **split across
time halves** — if the first half and the second half disagree, the relationship
is dying and the pooled number is misleading.

Two measurements:

  `recurrence()`      given anchor X shocked, how often did dependent Y follow,
                      how often does X shock, and how long until the next one
  `news_sensitivity()` which assets move most on event days relative to their
                      own baseline — i.e. which are worth watching at all
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .skips import record_skip
from .stats import wilson_interval

TRADING_DAYS_PER_YEAR = 252.0


# ------------------------------------------------------------- recurrence

@dataclass(frozen=True)
class Recurrence:
    anchor: str
    dependent: str
    sigma: float
    horizon_bars: int

    n_anchor_shocks: int
    n_followed: int
    follow_rate: float
    follow_lower: float
    follow_upper: float
    base_rate: float

    shocks_per_year: float
    expected_days_to_next: float
    years_covered: float

    median_response_pct: float
    q10_pct: float
    q90_pct: float

    first_half_rate: float
    second_half_rate: float

    @property
    def lift(self) -> float:
        return self.follow_rate - self.base_rate

    @property
    def decaying(self) -> bool:
        """Second half materially worse than the first: the relation is fading."""
        return (self.second_half_rate + 0.08) < self.first_half_rate

    @property
    def trustworthy(self) -> bool:
        return (self.n_anchor_shocks >= 30
                and self.follow_lower > self.base_rate
                and not self.decaying)

    def render(self) -> str:
        lines = [
            f"{self.dependent} following a {self.sigma:g}σ move in {self.anchor}",
            f"  happened {self.n_followed} times out of {self.n_anchor_shocks} shocks "
            f"over {self.years_covered:.1f} years",
            f"  rate {self.follow_rate:.0%}  (90% CI {self.follow_lower:.0%}"
            f"–{self.follow_upper:.0%})   base rate {self.base_rate:.0%}"
            f"   lift {self.lift:+.0%}",
            f"  {self.anchor} shocks {self.shocks_per_year:.1f}x/year — next one due in "
            f"~{self.expected_days_to_next:.0f} trading days on average",
            f"  when it follows: median {self.median_response_pct:+.2%} "
            f"(10–90% {self.q10_pct:+.2%} to {self.q90_pct:+.2%})",
            f"  stability: first half {self.first_half_rate:.0%} -> "
            f"second half {self.second_half_rate:.0%}",
        ]
        if self.decaying:
            lines.append("  WARNING: the rate is falling over time. The pooled number "
                         "overstates what you would get now.")
        if self.n_anchor_shocks < 30:
            lines.append(f"  WARNING: {self.n_anchor_shocks} shocks is too few to rely on.")
        return "\n".join(lines)


def _shock_mask(returns: pd.Series, sigma: float, vol_window: int) -> pd.Series:
    """|z| >= sigma using TRAILING volatility, shifted so no same-day info leaks."""
    vol = returns.rolling(vol_window).std().shift(1)
    return (returns / vol).abs() >= sigma


def recurrence(anchor: pd.Series, dependent: pd.Series,
               anchor_name: str, dependent_name: str,
               sigma: float = 2.0, horizon_bars: int = 1,
               vol_window: int = 60) -> Recurrence | None:
    """Count how often `dependent` moved with `anchor` after an anchor shock.

    "Followed" means the dependent's forward return over `horizon_bars` has the
    same sign as the anchor's shock. Direction only — magnitude is reported
    separately as a distribution rather than folded into a single number.
    """
    df = pd.concat([anchor.rename("a"), dependent.rename("d")], axis=1).dropna()
    if len(df) < vol_window + 250:
        return None

    a, d = df["a"], df["d"]
    fwd = d.shift(-horizon_bars).rolling(horizon_bars).sum() if horizon_bars > 1 \
        else d.shift(-1)
    aligned_all = (fwd * np.sign(a)).dropna()
    if aligned_all.empty:
        return None

    shocks = _shock_mask(a, sigma, vol_window)
    events = aligned_all[shocks.reindex(aligned_all.index, fill_value=False)]
    if len(events) < 5:
        return None

    followed = float((events > 0).sum())
    lo, hi = wilson_interval(followed, len(events), 0.90)
    years = len(df) / TRADING_DAYS_PER_YEAR
    per_year = len(events) / years if years > 0 else 0.0

    mid = len(events) // 2
    first = float((events.iloc[:mid] > 0).mean()) if mid else float("nan")
    second = float((events.iloc[mid:] > 0).mean()) if mid else float("nan")

    return Recurrence(
        anchor=anchor_name, dependent=dependent_name, sigma=sigma,
        horizon_bars=horizon_bars,
        n_anchor_shocks=int(len(events)), n_followed=int(followed),
        follow_rate=followed / len(events), follow_lower=float(lo), follow_upper=float(hi),
        base_rate=float((aligned_all > 0).mean()),
        shocks_per_year=float(per_year),
        expected_days_to_next=float(TRADING_DAYS_PER_YEAR / per_year) if per_year else float("inf"),
        years_covered=float(years),
        median_response_pct=float(events.median()),
        q10_pct=float(np.quantile(events, 0.10)),
        q90_pct=float(np.quantile(events, 0.90)),
        first_half_rate=first, second_half_rate=second,
    )


def recurrence_table(returns: dict[str, pd.Series], anchors: list[str],
                     dependents: list[str], sigma: float = 2.0,
                     min_shocks: int = 30) -> pd.DataFrame:
    """Every anchor x dependent pair, ranked by lift over base rate.

    No significance filter is applied here — this is a frequency table, and you
    should see the whole thing. Use `Recurrence.trustworthy` to filter, and
    remember that scanning many pairs and reading the top one is a selection.
    """
    rows = []
    for a in anchors:
        if a not in returns:
            continue
        for dep in dependents:
            if dep == a or dep not in returns:
                continue
            r = recurrence(returns[a], returns[dep], a, dep, sigma)
            if r is None or r.n_anchor_shocks < min_shocks:
                continue
            rows.append(dict(
                anchor=a, dependent=dep, shocks=r.n_anchor_shocks,
                followed=r.n_followed, rate=r.follow_rate, lower=r.follow_lower,
                base=r.base_rate, lift=r.lift, per_year=r.shocks_per_year,
                days_to_next=r.expected_days_to_next,
                median_move=r.median_response_pct,
                h1=r.first_half_rate, h2=r.second_half_rate,
                decaying=r.decaying, trustworthy=r.trustworthy,
            ))
    df = pd.DataFrame(rows)
    return df.sort_values("lift", ascending=False).reset_index(drop=True) if len(df) else df


# ------------------------------------------------------- news sensitivity

@dataclass(frozen=True)
class NewsSensitivity:
    symbol: str
    n_event_days: int
    n_normal_days: int
    mean_abs_event: float
    mean_abs_normal: float
    amplification: float          # event-day movement / normal-day movement
    reversion_rate: float         # how often the next day gives it back

    def render(self) -> str:
        return (
            f"{self.symbol}: moves {self.amplification:.1f}x more on event days "
            f"({self.mean_abs_event:.2%} vs {self.mean_abs_normal:.2%})\n"
            f"  {self.n_event_days} event days observed; "
            f"{self.reversion_rate:.0%} of them partly reversed the next day"
        )


def volume_event_days(bars: pd.DataFrame, z_threshold: float = 2.0,
                      window: int = 60) -> pd.Series:
    """PROXY for news days: abnormal volume.

    Labelled a proxy on purpose. Volume spikes on news, but also on rebalances,
    expiries and index flows. If you can supply real publication dates, pass
    them instead — `news_sensitivity` takes any boolean series.
    """
    v = bars["volume"].astype(float)
    z = (v - v.rolling(window).mean()) / v.rolling(window).std()
    return (z.shift(1).fillna(0) >= z_threshold)


def news_sensitivity(returns: pd.Series, event_days: pd.Series,
                     symbol: str) -> NewsSensitivity | None:
    """How much more does this asset move on event days than on ordinary ones?

    High amplification means the asset is worth watching for news — not that
    news predicts its direction. Those are different claims, and only the first
    one is measured here.
    """
    df = pd.concat([returns.rename("r"), event_days.rename("e")], axis=1).dropna()
    if len(df) < 250:
        return None
    ev = df[df["e"].astype(bool)]["r"]
    normal = df[~df["e"].astype(bool)]["r"]
    if len(ev) < 20 or len(normal) < 100:
        return None

    nxt = df["r"].shift(-1)
    paired = pd.concat([df["r"], nxt.rename("n"), df["e"]], axis=1).dropna()
    paired = paired[paired["e"].astype(bool)]
    reversion = float((np.sign(paired["n"]) != np.sign(paired["r"])).mean()) if len(paired) else float("nan")

    mae, man = float(ev.abs().mean()), float(normal.abs().mean())
    return NewsSensitivity(
        symbol=symbol, n_event_days=int(len(ev)), n_normal_days=int(len(normal)),
        mean_abs_event=mae, mean_abs_normal=man,
        amplification=mae / man if man > 0 else float("nan"),
        reversion_rate=reversion,
    )


def sensitivity_ranking(bars_by_symbol: dict[str, pd.DataFrame],
                        z_threshold: float = 2.0) -> pd.DataFrame:
    """Rank a universe by how strongly each name reacts to event days."""
    rows = []
    for sym, bars in bars_by_symbol.items():
        try:
            r = np.log(bars["close"].astype(float)).diff().dropna()
            ev = volume_event_days(bars, z_threshold)
            s = news_sensitivity(r, ev.reindex(r.index, fill_value=False), sym)
        except Exception as exc:  # noqa: BLE001
            record_skip("sensitivity", sym, exc)
            continue
        if s is None:
            continue
        rows.append(dict(symbol=sym, event_days=s.n_event_days,
                         event_move=s.mean_abs_event, normal_move=s.mean_abs_normal,
                         amplification=s.amplification, reversion=s.reversion_rate))
    df = pd.DataFrame(rows)
    return df.sort_values("amplification", ascending=False).reset_index(drop=True) if len(df) else df
