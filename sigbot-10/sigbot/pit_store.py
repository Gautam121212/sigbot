"""Point-in-time price store — what the data looked like when you fetched it.

Honest constraint: this cannot recover history you never downloaded. Yahoo has
already rewritten every bar it was going to rewrite before today, and no store
built now un-rewrites them. What it does is make every future rewrite visible
and every future backtest reproducible. The value starts accruing from the first
download, not retroactively, and anything claiming otherwise is selling you a
time machine.

Largest risk: it creates a feeling of rigour that outruns the data. A backtest
reading from a store seeded today is exactly as adjustment-contaminated as one
reading yfinance directly — the store simply stops it getting worse. Treat any
result over a period predating your first download with the same suspicion as
before.

Test gap: the reconciliation path is tested against synthetic rewrites, not
against a real Yahoo adjustment, because that would need a live split and a
month of waiting. The detection logic is the same either way; the timing is not.

## How it stores

Every fetch writes a snapshot: the bar as delivered, the timestamp of the
download, and the source. A later fetch of the same bar writes a *second* row
rather than overwriting the first. `get_bars(as_of=...)` then returns what was
known on that date, which is the property backtests need and the reason the
table has no unique constraint on (asset, bar_time) alone.

Storage cost is the obvious objection. A daily bar re-fetched weekly for a year
is 52 rows where one would do, so `insert_frame` writes a new snapshot only when
the values actually differ from the newest one held. Identical re-fetches cost
nothing.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

COLUMNS = ("open", "high", "low", "close", "volume")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    asset        TEXT NOT NULL,
    bar_time     TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    source       TEXT NOT NULL,
    open         REAL NOT NULL,
    high         REAL NOT NULL,
    low          REAL NOT NULL,
    close        REAL NOT NULL,
    volume       REAL NOT NULL,
    -- What was known about corporate actions at download time. Null means the
    -- source did not say, which is different from saying there were none.
    split_ratio  REAL,
    dividend     REAL
);
-- No unique constraint on (asset, bar_time): a bar legitimately has several
-- snapshots, one per time its value changed. That is the whole point.
CREATE INDEX IF NOT EXISTS ix_bars_lookup ON bars(asset, bar_time, downloaded_at);
CREATE INDEX IF NOT EXISTS ix_bars_asset ON bars(asset, downloaded_at);
"""


@dataclass(frozen=True)
class Rewrite:
    asset: str
    bar_time: str
    field: str
    was: float
    now: float
    first_seen: str
    changed_at: str

    @property
    def ratio(self) -> float:
        return self.now / self.was if self.was else float("inf")

    def render(self) -> str:
        hint = ""
        if 0.05 < self.ratio < 0.95 or 1.05 < self.ratio < 20:
            hint = f"  ratio {self.ratio:.3f} — consistent with a split or dividend"
        return (f"{self.asset} {self.bar_time[:10]} {self.field}: "
                f"{self.was:.4f} -> {self.now:.4f}\n"
                f"  first seen {self.first_seen[:10]}, changed by {self.changed_at[:10]}"
                + (f"\n{hint}" if hint else ""))


class PitStore:
    def __init__(self, path: str | Path = "pit_store.db"):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as con:
            # WAL lets readers work while a writer holds the file. Without it
            # a system polling several markets at once eventually returns
            # "database is locked", which surfaces as a data outage rather than
            # as the contention it actually is. Persistent once set, so this is
            # a one-time property of the file, not a per-connection setting.
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            con.commit()

    # ------------------------------------------------------------- writing
    def insert_frame(self, asset: str, bars: pd.DataFrame, source: str,
                     downloaded_at: datetime | None = None,
                     splits: pd.Series | None = None,
                     dividends: pd.Series | None = None) -> int:
        """Store a frame. Returns the number of snapshots actually written.

        A bar is written only when it differs from the newest snapshot already
        held, so re-fetching unchanged history costs nothing. That is what makes
        weekly refetching affordable, and refetching is what makes rewrites
        detectable at all.
        """
        if bars is None or bars.empty:
            return 0
        missing = [c for c in COLUMNS if c not in bars.columns]
        if missing:
            raise ValueError(f"{asset}: frame is missing {missing}")

        when = (downloaded_at or datetime.now(timezone.utc)).isoformat()
        latest = self._latest_values(asset)
        rows = []
        for ts, row in bars.iterrows():
            key = pd.Timestamp(ts).isoformat()
            values = tuple(round(float(row[c]), 6) for c in COLUMNS)
            if latest.get(key) == values:
                continue                    # unchanged since the last snapshot
            rows.append((asset, key, when, source, *values,
                         _at(splits, ts), _at(dividends, ts)))

        if not rows:
            return 0
        with closing(sqlite3.connect(self.path)) as con:
            con.executemany(
                "INSERT INTO bars(asset,bar_time,downloaded_at,source,"
                "open,high,low,close,volume,split_ratio,dividend) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            con.commit()
        return len(rows)

    def _latest_values(self, asset: str) -> dict[str, tuple]:
        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute(
                "SELECT bar_time, open, high, low, close, volume FROM bars b "
                "WHERE asset=? AND downloaded_at = ("
                "  SELECT MAX(downloaded_at) FROM bars WHERE asset=b.asset "
                "  AND bar_time=b.bar_time)", (asset,)).fetchall()
        return {r[0]: tuple(round(float(v), 6) for v in r[1:]) for r in rows}

    # ------------------------------------------------------------- reading
    def get_bars(self, asset: str, start: str | None = None, end: str | None = None,
                 as_of: str | datetime | None = None) -> pd.DataFrame:
        """Bars as known on `as_of`. Omit it for the newest view.

        This is the function backtests must use. Reading the newest view for a
        period you are backtesting reintroduces exactly the retroactive
        adjustment the store exists to keep out.
        """
        cutoff = (as_of.isoformat() if isinstance(as_of, datetime)
                  else (as_of or "9999-12-31"))
        q = ("SELECT bar_time, open, high, low, close, volume FROM bars b "
             "WHERE asset=? AND downloaded_at <= ? AND downloaded_at = ("
             "  SELECT MAX(downloaded_at) FROM bars WHERE asset=b.asset "
             "  AND bar_time=b.bar_time AND downloaded_at <= ?)")
        args: list = [asset, cutoff, cutoff]
        if start:
            q += " AND bar_time >= ?"
            args.append(start)
        if end:
            q += " AND bar_time <= ?"
            args.append(end)
        q += " ORDER BY bar_time"

        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute(q, args).fetchall()
        if not rows:
            return pd.DataFrame(columns=list(COLUMNS))
        df = pd.DataFrame(rows, columns=["bar_time", *COLUMNS])
        df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("bar_time")))
        return df

    def snapshots(self, asset: str, bar_time: str) -> list[dict]:
        """Every version of one bar, oldest first."""
        cols = ("downloaded_at", "source", *COLUMNS)
        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute(
                "SELECT downloaded_at,source,open,high,low,close,volume FROM bars "
                "WHERE asset=? AND bar_time=? ORDER BY downloaded_at", (asset, bar_time)
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    # ------------------------------------------------------- reconciliation
    def rewrites(self, asset: str | None = None, field: str = "close",
                 tolerance: float = 1e-6) -> list[Rewrite]:
        """Bars whose stored value changed between downloads.

        A rewrite is not necessarily wrong — a split adjustment is correct and
        expected. It is *undisclosed* that matters: a backtest that silently
        used the new value for an old date was reading the future.
        """
        if field not in COLUMNS:
            raise ValueError(f"{field} is not a price column")

        # All five columns are selected and the one wanted is picked in Python.
        # `field` is already whitelisted, so concatenating it would be safe —
        # but a query built by concatenation invites the next person to skip the
        # check, and the cost of not doing it here is four unused floats.
        base = ("SELECT asset, bar_time, downloaded_at, open, high, low, close, "
                "volume FROM bars")
        order = " ORDER BY asset, bar_time, downloaded_at"
        pos = 3 + COLUMNS.index(field)
        with closing(sqlite3.connect(self.path)) as con:
            if asset:
                cursor = con.execute(base + " WHERE asset=?" + order, (asset,))
            else:
                cursor = con.execute(base + order)
            rows = [(r[0], r[1], r[2], r[pos]) for r in cursor]

        out: list[Rewrite] = []
        seen: dict[tuple[str, str], tuple[str, float]] = {}
        for a, t, when, value in rows:
            key = (a, t)
            if key in seen:
                first_when, first_value = seen[key]
                if abs(float(value) - first_value) > tolerance:
                    out.append(Rewrite(a, t, field, first_value, float(value),
                                       first_when, when))
                    seen[key] = (first_when, float(value))
            else:
                seen[key] = (when, float(value))
        return out

    # ------------------------------------------------------------ metadata
    def coverage(self, asset: str) -> dict:
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT COUNT(DISTINCT bar_time), COUNT(*), MIN(bar_time), "
                "MAX(bar_time), MIN(downloaded_at), COUNT(DISTINCT source) "
                "FROM bars WHERE asset=?", (asset,)).fetchone()
        bars, snaps, first, last, since, sources = row
        return {"asset": asset, "bars": bars or 0, "snapshots": snaps or 0,
                "first_bar": first, "last_bar": last,
                "recording_since": since, "sources": sources or 0}

    def assets(self) -> list[str]:
        with closing(sqlite3.connect(self.path)) as con:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT asset FROM bars ORDER BY asset")]

    def summary(self) -> str:
        names = self.assets()
        if not names:
            return ("Point-in-time store is empty. It records what each fetch "
                    "returned, so its value begins at the first download and "
                    "cannot reach backwards.")
        total = sum(self.coverage(a)["snapshots"] for a in names)
        extra = total - sum(self.coverage(a)["bars"] for a in names)
        since = min(self.coverage(a)["recording_since"] or "" for a in names)
        return (f"{len(names)} assets, {total:,} snapshots, recording since "
                f"{since[:10]}. {extra:,} of those are re-writes of a bar that "
                "changed after it was first seen."
                + ("" if extra else " No rewrites detected yet."))


def _at(series: pd.Series | None, ts) -> float | None:
    if series is None:
        return None
    try:
        value = series.get(ts)
    except (TypeError, KeyError):
        return None
    return None if value is None or pd.isna(value) else float(value)
