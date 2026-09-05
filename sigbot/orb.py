"""Opening range breakout — the whole strategy, backtested, in one file.

Deliberately small. The point of this module is that it ends the architecture
spiral rather than extending it: one instrument, one rule set, a trade list, and
a Wilson bound on the result.

Three things it does that the proposed plan did not.

**No tuning loop.** The plan said: if the win rate comes in under 55%, adjust a
parameter and retest. That is fitting the rule to the test set, and it is the
same selection bias measured earlier in this project (+10pp on the reported
rate). `sensitivity()` sweeps the grid and shows you the whole surface at once
instead. An edge that exists in one cell and vanishes in its neighbours is an
artifact; an edge that survives the neighbourhood is worth paper trading.

**R is reported, not just win rate.** With a stop at the opposite range edge and
a 1.5R target, breakeven is a 40% win rate. A 55% win rate is +0.375R per trade
and a 64% win rate is +0.600R. Win rate alone cannot tell you which.

**Credit-spread win rates get their breakeven computed.** See
`credit_spread_breakeven` below — the reason those 89%/83% figures cannot be
acted on as quoted.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .stats import wilson_interval


@dataclass(frozen=True)
class ORBRules:
    range_minutes: int = 15
    session_open: str = "09:30"
    entry_cutoff: str = "10:30"
    volume_multiple: float = 1.5
    target_r: float = 1.5
    min_range_pct: float = 0.002
    cost_per_side: float = 0.01      # price units; ~1c round trip on SPY
    min_vix: float | None = 18.0     # previous close; None disables the filter


@dataclass(frozen=True)
class Trade:
    date: pd.Timestamp
    side: str
    entry: float
    stop: float
    target: float
    exit_price: float
    r_multiple: float
    exit_reason: str


def backtest_orb(bars: pd.DataFrame, rules: ORBRules = ORBRules(),
                 vix_prev_close: pd.Series | None = None) -> list[Trade]:
    """One trade per session, at most. `bars` needs a tz-naive exchange-local index."""
    trades: list[Trade] = []
    open_t = pd.Timestamp(rules.session_open).time()
    cut_t = pd.Timestamp(rules.entry_cutoff).time()

    for day, session in bars.groupby(bars.index.normalize()):
        session = session.sort_index()
        session = session[session.index.time >= open_t]
        if len(session) < 3:
            continue
        if rules.min_vix is not None and vix_prev_close is not None:
            v = vix_prev_close.reindex([day]).iloc[0]
            if not np.isfinite(v) or v < rules.min_vix:
                continue

        end = session.index[0] + pd.Timedelta(minutes=rules.range_minutes)
        rng = session[session.index < end]
        rest = session[(session.index >= end) & (session.index.time <= cut_t)]
        if rng.empty or rest.empty:
            continue

        hi, lo = float(rng["high"].max()), float(rng["low"].min())
        ref = float(rng["open"].iloc[0])
        if ref <= 0 or (hi - lo) / ref < rules.min_range_pct:
            continue          # range too tight: no room between entry and stop
        vol_bar = float(rng["volume"].mean())

        trade = None
        for ts, bar in rest.iterrows():
            if bar["volume"] < rules.volume_multiple * vol_bar:
                continue
            if bar["high"] >= hi:
                trade = ("BUY", hi, lo)
            elif bar["low"] <= lo:
                trade = ("SELL", lo, hi)
            if trade:
                entry_ts = ts
                break
        if not trade:
            continue

        side, entry, stop = trade
        sign = 1.0 if side == "BUY" else -1.0
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + sign * rules.target_r * risk

        after = session[session.index > entry_ts]
        exit_price, reason = float(session["close"].iloc[-1]), "session_close"
        for _, bar in after.iterrows():
            hit_stop = bar["low"] <= stop if side == "BUY" else bar["high"] >= stop
            hit_tgt = bar["high"] >= target if side == "BUY" else bar["low"] <= target
            if hit_stop and hit_tgt:
                exit_price, reason = stop, "ambiguous_bar_counted_as_stop"
                break
            if hit_stop:
                exit_price, reason = stop, "stop"
                break
            if hit_tgt:
                exit_price, reason = target, "target"
                break

        gross = sign * (exit_price - entry)
        r = (gross - 2 * rules.cost_per_side) / risk
        trades.append(Trade(day, side, entry, stop, target, exit_price, float(r), reason))
    return trades


@dataclass(frozen=True)
class ORBResult:
    n: int
    win_rate: float
    win_lower: float
    mean_r: float
    total_r: float
    max_drawdown_r: float
    t_stat: float

    def summary(self) -> str:
        if self.n == 0:
            return "no trades triggered"
        return (
            f"trades {self.n}\n"
            f"win rate {self.win_rate:.1%}  (90% lower bound {self.win_lower:.1%})\n"
            f"mean {self.mean_r:+.3f}R   total {self.total_r:+.1f}R   "
            f"max drawdown {self.max_drawdown_r:.1f}R\n"
            f"t-stat {self.t_stat:+.2f}"
        )


def evaluate(trades: list[Trade]) -> ORBResult:
    if not trades:
        return ORBResult(0, float("nan"), 0.0, float("nan"), 0.0, 0.0, float("nan"))
    r = np.array([t.r_multiple for t in trades])
    wins = float((r > 0).sum())
    equity = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    se = r.std(ddof=1) / np.sqrt(r.size) if r.size > 1 else np.nan
    return ORBResult(
        n=r.size,
        win_rate=wins / r.size,
        win_lower=wilson_interval(wins, r.size, 0.90)[0],
        mean_r=float(r.mean()),
        total_r=float(equity[-1]),
        max_drawdown_r=float((equity - peak).min()),
        t_stat=float(r.mean() / se) if se and np.isfinite(se) and se > 0 else float("nan"),
    )


def sensitivity(bars: pd.DataFrame, base: ORBRules = ORBRules(),
                vol_grid=(1.0, 1.25, 1.5, 2.0), target_grid=(1.0, 1.5, 2.0),
                vix_prev_close: pd.Series | None = None) -> pd.DataFrame:
    """Sweep the parameter neighbourhood and return the whole surface.

    This is a robustness check, not a search. Reading it as "pick the best cell"
    reintroduces exactly the selection bias the rest of this project exists to
    avoid — the best cell of twelve is the best of twelve draws, not an estimate.
    Look instead at whether the sign of mean R is stable across the grid.
    """
    rows = []
    for vm in vol_grid:
        for tr in target_grid:
            rules = ORBRules(**{**base.__dict__, "volume_multiple": vm, "target_r": tr})
            res = evaluate(backtest_orb(bars, rules, vix_prev_close))
            rows.append(dict(volume_multiple=vm, target_r=tr, n=res.n,
                             win_rate=res.win_rate, mean_r=res.mean_r,
                             total_r=res.total_r))
    return pd.DataFrame(rows)


def credit_spread_breakeven(width: float, credit: float) -> float:
    """Win rate at which a defined-risk credit spread breaks even, before costs.

    A 1-wide spread sold for 0.15 needs 85% just to break even, so a quoted 83%
    win rate is a losing strategy. Win rate is not edge when payoffs are
    asymmetric, and a win rate quoted without the credit and the width cannot be
    evaluated at all.
    """
    if not (0 < credit < width):
        raise ValueError("credit must be between 0 and the spread width")
    risk = width - credit
    return risk / (risk + credit)


def synthetic_intraday(days: int = 250, bar_minutes: int = 15, seed: int = 3,
                       annual_vol: float = 0.16, start: str = "2024-01-02") -> pd.DataFrame:
    """Driftless intraday bars with no breakout structure whatsoever.

    The null control for this strategy: run the backtest on it and the win rate
    should land near the level implied by a 1.5R target on random data (~40%),
    with mean R near zero. Anything better means a bug.
    """
    rng = np.random.default_rng(seed)
    per_day = int(390 / bar_minutes)
    sd = annual_vol / np.sqrt(252 * per_day)
    idx, rows, price = [], [], 500.0
    for d in pd.bdate_range(start, periods=days):
        t = pd.Timestamp(d) + pd.Timedelta(hours=9, minutes=30)
        for _ in range(per_day):
            r = rng.normal(0, sd)
            close = price * np.exp(r)
            wick = abs(rng.normal(0, sd)) * price
            rows.append(dict(open=price,
                             high=max(price, close) + wick,
                             low=min(price, close) - wick,
                             close=close,
                             volume=rng.lognormal(12, 0.35)))
            idx.append(t)
            t += pd.Timedelta(minutes=bar_minutes)
            price = close
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))
