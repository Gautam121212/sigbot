"""Shadow ledger.

Every prediction from both models is written here before it is sent, and
resolved against realised prices afterwards. This is the only mechanism that
can ever justify a probability on the news model, and it is the audit trail
that lets you check whether the daily model's live behaviour matches its
backtest.

Nothing is deleted. If a prediction was made, it stays in the ledger whether
it worked or not. Silent pruning of losers is how backtests become fiction.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .stats import wilson_interval
from .tiers import Failure, Tier, classify_outcome, classify_tier

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    model         TEXT    NOT NULL,          -- 'news' | 'daily'
    symbol        TEXT    NOT NULL,
    side          TEXT    NOT NULL,
    score         REAL,
    expected_move REAL,
    created_at    TEXT    NOT NULL,          -- ISO8601 UTC
    resolve_after TEXT    NOT NULL,
    entry_price   REAL,
    exit_price    REAL,
    realised_ret  REAL,
    hit           INTEGER,                   -- NULL until resolved
    outcome_mode  TEXT,                      -- see tiers.Failure
    alerted       INTEGER NOT NULL DEFAULT 1, -- 0 = measured only, never sent
    payload       TEXT
);
CREATE INDEX IF NOT EXISTS ix_pred_open ON predictions(model, hit, resolve_after);
CREATE INDEX IF NOT EXISTS ix_pred_symbol ON predictions(model, symbol, hit);

-- Every job run, whether or not it produced anything. Without this, a day when
-- the models correctly held on all 100 assets is indistinguishable from a day
-- the job never ran, and the health check reports "no predictions made" on a
-- system that is working exactly as intended.
CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job        TEXT NOT NULL,
    ran_at     TEXT NOT NULL,
    considered INTEGER,
    signals    INTEGER,
    note       TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_job ON runs(job, ran_at);
"""


class ShadowLedger:
    def __init__(self, path: str | Path = "shadow.db"):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as con:
            # WAL lets readers work while a writer holds the file. Without it
            # a system polling several markets at once eventually returns
            # "database is locked", which surfaces as a data outage rather than
            # as the contention it actually is. Persistent once set, so this is
            # a one-time property of the file, not a per-connection setting.
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            cols = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
            if "outcome_mode" not in cols:  # migrate ledgers created before tiering
                con.execute("ALTER TABLE predictions ADD COLUMN outcome_mode TEXT")
            if "alerted" not in cols:
                con.execute("ALTER TABLE predictions ADD COLUMN alerted "
                            "INTEGER NOT NULL DEFAULT 1")
            con.commit()

    def log_run(self, job: str, considered: int = 0, signals: int = 0,
                note: str = "") -> None:
        """Record that a job ran. A quiet day is not a missing day."""
        with closing(sqlite3.connect(self.path)) as con:
            con.execute(
                "INSERT INTO runs(job,ran_at,considered,signals,note) VALUES (?,?,?,?,?)",
                (job, datetime.now(timezone.utc).isoformat(), considered, signals, note))
            con.commit()

    def last_run(self, job: str) -> dict | None:
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT job,ran_at,considered,signals,note FROM runs "
                "WHERE job=? ORDER BY ran_at DESC LIMIT 1", (job,)).fetchone()
        cols = ("job", "ran_at", "considered", "signals", "note")
        return dict(zip(cols, row)) if row else None

    def record(self, model: str, symbol: str, side: str, score: float | None,
               expected_move: float | None, entry_price: float | None,
               horizon_hours: int = 24, payload: str = "", alerted: bool = True) -> int:
        now = datetime.now(timezone.utc)
        with closing(sqlite3.connect(self.path)) as con:
            cur = con.execute(
                "INSERT INTO predictions(model,symbol,side,score,expected_move,"
                "created_at,resolve_after,entry_price,payload,alerted) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (model, symbol, side, score, expected_move, now.isoformat(),
                 (now + timedelta(hours=horizon_hours)).isoformat(), entry_price,
                 payload, int(alerted)),
            )
            con.commit()
            return int(cur.lastrowid or 0)

    def due(self, model: str | None = None) -> list[tuple[int, str, str, float | None]]:
        now = datetime.now(timezone.utc).isoformat()
        q = ("SELECT id,symbol,side,entry_price FROM predictions "
             "WHERE hit IS NULL AND resolve_after <= ?")
        args: list[object] = [now]
        if model:
            q += " AND model = ?"
            args.append(model)
        with closing(sqlite3.connect(self.path)) as con:
            return list(con.execute(q, args))

    def resolve(self, pred_id: int, exit_price: float,
                bar_open: float | None = None, bar_high: float | None = None,
                bar_low: float | None = None, cost_pct: float = 0.0015) -> None:
        """Score a prediction and classify HOW it failed, when the bar is available.

        The OHLC arguments are optional so an exit price alone still resolves;
        without them the outcome mode is coarser but never invented.
        """
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT side, entry_price FROM predictions WHERE id = ?", (pred_id,)
            ).fetchone()
            if not row or row[1] in (None, 0):
                return
            side, entry = row[0], float(row[1])
            ret = exit_price / entry - 1.0
            mode, _net = classify_outcome(side, entry, bar_open, bar_high, bar_low,
                                          exit_price, cost_pct)
            # `hit` is taken from the same classification, not from the gross
            # sign. They used to disagree: a +0.05% move counted as a win in the
            # hit rate and as `magnitude_short` in the breakdown. Being right by
            # less than it costs to trade is not a win, and scoring it as one
            # inflated every hit rate in the system.
            con.execute(
                "UPDATE predictions SET exit_price=?, realised_ret=?, hit=?, "
                "outcome_mode=? WHERE id=?",
                (exit_price, ret, 1 if mode is Failure.WIN else 0, mode.value, pred_id),
            )
            con.commit()

    def failure_modes(self, model: str, symbol: str | None = None) -> dict[str, int]:
        q = ("SELECT outcome_mode, COUNT(*) FROM predictions "
             "WHERE model=? AND outcome_mode IS NOT NULL")
        args: list[object] = [model]
        if symbol:
            q += " AND symbol = ?"
            args.append(symbol)
        with closing(sqlite3.connect(self.path)) as con:
            return {m: int(c) for m, c in con.execute(q + " GROUP BY outcome_mode", args)}

    def tier(self, model: str, symbol: str, conf: float = 0.90) -> tuple[Tier, float, int]:
        """Evidence tier for one asset/model. Never time-based, never overridable."""
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT COUNT(*), SUM(hit) FROM predictions "
                "WHERE model=? AND symbol=? AND hit IS NOT NULL",
                (model, symbol),
            ).fetchone()
        n = int(row[0] or 0)
        hits = float(row[1] or 0)
        tier, lower = classify_tier(n, hits, conf)
        return tier, lower, n

    def recent(self, limit: int = 40, model: str | None = None,
               only_misses: bool = False) -> list[dict]:
        """Most recently resolved predictions, newest first.

        Feeds the learning and failure views. Both read the same rows: what the
        system saw and what actually happened. A miss is not a separate kind of
        record, it is the same record with a different outcome.
        """
        q = ("SELECT id,model,symbol,side,score,expected_move,created_at,"
             "entry_price,exit_price,realised_ret,hit,outcome_mode "
             "FROM predictions WHERE hit IS NOT NULL")
        args: list[object] = []
        if model:
            q += " AND model = ?"
            args.append(model)
        if only_misses:
            q += " AND hit = 0"
        q += " ORDER BY resolve_after DESC, id DESC LIMIT ?"
        args.append(int(limit))
        cols = ("id", "model", "symbol", "side", "score", "expected_move", "created_at",
                "entry_price", "exit_price", "realised_ret", "hit", "outcome_mode")
        with closing(sqlite3.connect(self.path)) as con:
            return [dict(zip(cols, r)) for r in con.execute(q, args)]

    def stats(self, model: str, conf: float = 0.90) -> dict[str, tuple[int, float, float]]:
        """symbol -> (n_resolved, hit_rate, wilson_lower)."""
        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute(
                "SELECT symbol, COUNT(*), SUM(hit) FROM predictions "
                "WHERE model=? AND hit IS NOT NULL GROUP BY symbol",
                (model,),
            ).fetchall()
        out = {}
        for symbol, n, hits in rows:
            hits = float(hits or 0)
            out[symbol] = (int(n), hits / n if n else float("nan"),
                           wilson_interval(hits, n, conf)[0])
        return out

    def overall(self, model: str, conf: float = 0.90) -> tuple[int, float, float]:
        with closing(sqlite3.connect(self.path)) as con:
            n, hits = con.execute(
                "SELECT COUNT(*), SUM(hit) FROM predictions WHERE model=? AND hit IS NOT NULL",
                (model,),
            ).fetchone()
        n = int(n or 0)
        hits = float(hits or 0)
        if n == 0:
            return 0, float("nan"), 0.0
        return n, hits / n, wilson_interval(hits, n, conf)[0]
