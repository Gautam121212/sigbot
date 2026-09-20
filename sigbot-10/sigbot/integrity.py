"""Data integrity — corrupt bars are worse than missing ones.

A missing bar produces no signal. A corrupt bar produces a confident one, and
nothing downstream can tell the difference. Every model in this project reads
OHLCV and trusts it completely.

Four checks, cheap enough to run on every fetch:

  shape        the columns exist and hold numbers
  consistency  high >= max(open, close), low <= min(open, close), high >= low
  sanity       no negative or zero prices, no negative volume
  freshness    the last bar is not older than the interval allows

`verify()` returns the problems rather than raising, so a caller can skip one
bad asset instead of losing the run. `require()` raises, for the places where
carrying on with bad data would be worse than stopping.

The point-in-time question is deliberately out of scope here. Yahoo rewrites old
bars for splits and dividends, and no checksum recovers what you never
downloaded. `fingerprint()` records what a frame looked like when you fetched
it, so a later change becomes detectable — but only going forward. Data already
gathered cannot be un-rewritten, and a store that claimed otherwise would be
worse than none.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

REQUIRED = ("open", "high", "low", "close", "volume")

# How stale a last bar may be before it is suspect, per interval.
MAX_AGE = {
    "1d": timedelta(days=5),      # long weekends and holidays
    "1h": timedelta(hours=12),
    "15m": timedelta(hours=6),
    "5m": timedelta(hours=3),
}


@dataclass
class Integrity:
    symbol: str
    rows: int
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        if self.ok and not self.warnings:
            return f"{self.symbol}: {self.rows} bars, clean"
        lines = [f"{self.symbol}: {self.rows} bars"]
        lines += [f"  PROBLEM {p}" for p in self.problems]
        lines += [f"  warning {w}" for w in self.warnings]
        return "\n".join(lines)


def verify(bars: pd.DataFrame, symbol: str = "?", interval: str = "1d",
           now: datetime | None = None) -> Integrity:
    """Check a price frame. Returns what is wrong rather than raising."""
    res = Integrity(symbol=symbol, rows=0 if bars is None else len(bars))
    if bars is None or bars.empty:
        res.problems.append("no rows")
        return res

    missing = [c for c in REQUIRED if c not in bars.columns]
    if missing:
        res.problems.append(f"missing columns {missing}")
        return res

    try:
        o, h, low, c, v = (bars[k].astype(float) for k in REQUIRED)
    except (TypeError, ValueError) as exc:
        res.problems.append(f"non-numeric price data ({type(exc).__name__})")
        return res

    finite = np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(c)
    if not finite.all():
        res.problems.append(f"{int((~finite).sum())} bars with NaN or infinite prices")

    if (c[finite] <= 0).any() or (o[finite] <= 0).any():
        res.problems.append("zero or negative prices")
    if (v < 0).any():
        res.problems.append("negative volume")

    # The definitional checks. A bar where the high is below the close did not
    # happen, and no amount of downstream care recovers from believing it.
    bad_high = (h < np.maximum(o, c)) & finite
    bad_low = (low > np.minimum(o, c)) & finite
    inverted = (h < low) & finite
    if bad_high.any():
        res.problems.append(f"{int(bad_high.sum())} bars where high < max(open, close)")
    if bad_low.any():
        res.problems.append(f"{int(bad_low.sum())} bars where low > min(open, close)")
    if inverted.any():
        res.problems.append(f"{int(inverted.sum())} bars where high < low")

    if not bars.index.is_monotonic_increasing:
        res.problems.append("timestamps are not in order")
    if bars.index.duplicated().any():
        res.problems.append(f"{int(bars.index.duplicated().sum())} duplicate timestamps")

    # Freshness is a warning: a stale feed is usually a holiday, occasionally a
    # dead ticker, and the caller is better placed to judge which.
    try:
        last = pd.Timestamp(bars.index[-1])
        ref = now or datetime.now(timezone.utc)
        ref_ts = pd.Timestamp(ref).tz_localize(None) if pd.Timestamp(ref).tz else pd.Timestamp(ref)
        age = ref_ts - (last.tz_localize(None) if last.tz else last)
        limit = MAX_AGE.get(interval, timedelta(days=5))
        if age > limit:
            res.warnings.append(f"last bar is {age.days}d old, over the "
                                f"{limit.days or limit.seconds // 3600}"
                                f"{'d' if limit.days else 'h'} limit for {interval}")
    except (TypeError, ValueError):
        res.warnings.append("timestamps could not be compared to the clock")

    # A single bar moving more than 50% is usually an unadjusted split, not news.
    if finite.sum() > 2:
        moves = c[finite].pct_change().abs()
        extreme = int((moves > 0.5).sum())
        if extreme:
            res.warnings.append(f"{extreme} single-bar moves over 50% — check for "
                                "an unadjusted split before trusting these")
    return res


def require(bars: pd.DataFrame, symbol: str = "?", interval: str = "1d") -> pd.DataFrame:
    """Verify and raise. For callers where bad data is worse than no run."""
    res = verify(bars, symbol, interval)
    if not res.ok:
        raise ValueError(f"{symbol} failed integrity: {'; '.join(res.problems)}")
    return bars


def fingerprint(bars: pd.DataFrame) -> str:
    """Stable digest of a frame's contents, for spotting a silent rewrite.

    Only useful going forward: it records what you were given today so a change
    tomorrow is visible. It cannot recover a bar that was already rewritten
    before you first saw it.
    """
    if bars is None or bars.empty:
        return hashlib.sha256(b"empty").hexdigest()[:16]
    cols = [c for c in REQUIRED if c in bars.columns]
    payload = bars[cols].round(6).to_csv().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def changed_since(bars: pd.DataFrame, previous: str) -> bool:
    return fingerprint(bars) != previous


def verify_all(frames: dict[str, pd.DataFrame], interval: str = "1d") -> list[Integrity]:
    return sorted((verify(b, s, interval) for s, b in frames.items()),
                  key=lambda r: (r.ok, not r.warnings, r.symbol))
