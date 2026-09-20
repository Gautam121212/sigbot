"""Adaptation — changing what it does because of why it was wrong.

The ledger already sorts every miss by cause: went the other way, right but too
small, started right then turned, gapped overnight. Nothing read those. The
system could tell you what went wrong and then made the identical assumption
the next day.

This closes that. Once an asset has enough resolved misses, the dominant cause
is diagnosed and one concrete thing changes:

    right but too small   the direction works and the horizon does not. Hold
                          longer, so the move has room to clear costs.
    started right, turned  it reached profit and gave it back. Exit sooner.
    gapped overnight      it moved before you could act. A next-day call on
                          this asset is measuring something you cannot trade.
    went the other way    there is no directional edge here. Hand it to the
                          board for replacement.

## Why this is safe to let run

Adaptation is where a learning system usually goes wrong: it chases noise,
overfits to a bad fortnight, and ends up tuned to the past. Four guards:

  * nothing happens below 40 resolved misses on that asset
  * the dominant cause must be at least 40% of them, so a scatter of unrelated
    failures changes nothing
  * one change per asset per 30 days
  * horizons are clamped to 6-72 hours, so no sequence of changes can walk the
    asset somewhere absurd

Every change is stored with the evidence that caused it and the date, and
`explain()` reads that back in plain words. An adaptation you cannot audit is
indistinguishable from a bug.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MIN_MISSES = 40
MIN_SHARE = 0.40
COOLDOWN_DAYS = 30
MIN_HOURS, MAX_HOURS = 6.0, 72.0
DEFAULT_HOURS = 24.0

# cause -> (hours delta, what it means, what changes)
RESPONSES: dict[str, tuple[float, str, str]] = {
    "magnitude_short": (
        +12.0,
        "the direction keeps being right but the move is smaller than the cost "
        "of trading it",
        "hold longer, so the move has room to clear costs"),
    "reversal": (
        -8.0,
        "it reaches profit and then gives it back before the horizon is up",
        "exit sooner, before the move unwinds"),
    "gap_against": (
        0.0,
        "it moves overnight, before there is any chance to act",
        "flag it as untradeable on a next-day horizon"),
    "direction_wrong": (
        0.0,
        "the direction is simply wrong, with no favourable move first",
        "no directional edge here — hand it to the board for replacement"),
    "unexplained": (
        0.0,
        "nothing in the price path explains the misses",
        "no change; an unexplained cause is not a cause"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS adaptations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model       TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    changed_at  TEXT NOT NULL,
    cause       TEXT NOT NULL,
    share       REAL NOT NULL,
    n_misses    INTEGER NOT NULL,
    old_hours   REAL,
    new_hours   REAL,
    untradeable INTEGER NOT NULL DEFAULT 0,
    retire      INTEGER NOT NULL DEFAULT 0,
    reason      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_adapt ON adaptations(model, symbol, changed_at);
"""


@dataclass
class Diagnosis:
    model: str
    symbol: str
    n_misses: int
    cause: str
    share: float
    old_hours: float
    new_hours: float
    untradeable: bool
    retire: bool
    reason: str

    @property
    def changes_anything(self) -> bool:
        return (abs(self.new_hours - self.old_hours) > 0.5
                or self.untradeable or self.retire)

    def render(self) -> str:
        _, meaning, action = RESPONSES.get(self.cause, RESPONSES["unexplained"])
        head = (f"{self.symbol} ({self.model}): {self.share:.0%} of "
                f"{self.n_misses} misses were '{self.cause.replace('_', ' ')}'")
        body = f"  {meaning.capitalize()}. So: {action}."
        if abs(self.new_hours - self.old_hours) > 0.5:
            body += f"\n  Horizon {self.old_hours:.0f}h -> {self.new_hours:.0f}h."
        if self.retire:
            body += "\n  Marked for replacement on the next rotation."
        if self.untradeable:
            body += "\n  Marked untradeable at this horizon."
        return head + "\n" + body


class Adaptations:
    """Per-asset adjustments, with the evidence that produced each one."""

    def __init__(self, path: str | Path = "adaptations.db"):
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

    # ----------------------------------------------------------- read state
    def hours_for(self, model: str, symbol: str, default: float = DEFAULT_HOURS) -> float:
        row = self._latest(model, symbol)
        return float(row["new_hours"]) if row and row["new_hours"] else default

    def is_untradeable(self, model: str, symbol: str) -> bool:
        row = self._latest(model, symbol)
        return bool(row and row["untradeable"])

    def retiring(self, model: str | None = None) -> list[str]:
        """Assets the failure record says should be replaced."""
        with closing(sqlite3.connect(self.path)) as con:
            if model is None:
                rows = con.execute("SELECT DISTINCT symbol FROM adaptations "
                                   "WHERE retire=1")
            else:
                rows = con.execute("SELECT DISTINCT symbol FROM adaptations "
                                   "WHERE retire=1 AND model=?", (model,))
            return [r[0] for r in rows]

    _LATEST_COLS = ("changed_at", "new_hours", "untradeable", "retire", "cause", "reason")

    def _latest(self, model: str, symbol: str) -> dict | None:
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT changed_at,new_hours,untradeable,retire,cause,reason "
                "FROM adaptations WHERE model=? AND symbol=? "
                "ORDER BY changed_at DESC LIMIT 1", (model, symbol)).fetchone()
        return dict(zip(self._LATEST_COLS, row)) if row else None

    def _in_cooldown(self, model: str, symbol: str) -> bool:
        row = self._latest(model, symbol)
        if not row:
            return False
        last = datetime.fromisoformat(row["changed_at"])
        return (datetime.now(timezone.utc) - last).days < COOLDOWN_DAYS

    # ------------------------------------------------------------- diagnose
    def diagnose(self, ledger, model: str = "daily") -> list[Diagnosis]:
        """Read the failure record and work out what to change. Writes nothing."""
        with closing(sqlite3.connect(ledger.path)) as con:
            rows = con.execute(
                "SELECT symbol, outcome_mode, COUNT(*) FROM predictions "
                "WHERE model=? AND hit=0 AND outcome_mode IS NOT NULL "
                "GROUP BY symbol, outcome_mode", (model,)).fetchall()

        by_symbol: dict[str, dict[str, int]] = {}
        for symbol, mode, count in rows:
            by_symbol.setdefault(symbol, {})[mode] = count

        out = []
        for symbol, modes in by_symbol.items():
            total = sum(modes.values())
            if total < MIN_MISSES or self._in_cooldown(model, symbol):
                continue
            cause, count = max(modes.items(), key=lambda kv: kv[1])
            share = count / total
            if share < MIN_SHARE:
                continue      # a scatter of unrelated failures is not a cause

            delta, _, _ = RESPONSES.get(cause, RESPONSES["unexplained"])
            old = self.hours_for(model, symbol)
            new = min(MAX_HOURS, max(MIN_HOURS, old + delta))
            out.append(Diagnosis(
                model=model, symbol=symbol, n_misses=total, cause=cause,
                share=share, old_hours=old, new_hours=new,
                untradeable=(cause == "gap_against"),
                retire=(cause == "direction_wrong"),
                reason=RESPONSES.get(cause, RESPONSES["unexplained"])[2]))
        return sorted(out, key=lambda d: -d.n_misses)

    def apply(self, diagnoses: list[Diagnosis]) -> list[Diagnosis]:
        """Persist the ones that actually change something."""
        applied = [d for d in diagnoses if d.changes_anything]
        now = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.path)) as con:
            con.executemany(
                "INSERT INTO adaptations(model,symbol,changed_at,cause,share,"
                "n_misses,old_hours,new_hours,untradeable,retire,reason) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(d.model, d.symbol, now, d.cause, d.share, d.n_misses,
                  d.old_hours, d.new_hours, int(d.untradeable), int(d.retire),
                  d.reason) for d in applied])
            con.commit()
        return applied

    _HISTORY_COLS = ("model", "symbol", "changed_at", "cause", "share", "n_misses",
                     "old_hours", "new_hours", "untradeable", "retire", "reason")

    def history(self, limit: int = 20) -> list[dict]:
        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute(
                "SELECT model,symbol,changed_at,cause,share,n_misses,old_hours,"
                "new_hours,untradeable,retire,reason FROM adaptations "
                "ORDER BY changed_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(self._HISTORY_COLS, r)) for r in rows]

    def explain(self, limit: int = 8) -> str:
        rows = self.history(limit)
        if not rows:
            return ("No adaptations yet. Nothing changes until an asset has "
                    f"{MIN_MISSES} resolved misses with one cause behind at least "
                    f"{MIN_SHARE:.0%} of them.")
        out = ["What it changed, and why:"]
        for r in rows:
            when = r["changed_at"][:10]
            line = (f"  {when}  {r['symbol']} — {r['share']:.0%} of {r['n_misses']} "
                    f"misses were '{r['cause'].replace('_', ' ')}'. {r['reason']}.")
            if r["old_hours"] and abs(r["new_hours"] - r["old_hours"]) > 0.5:
                line += f" Horizon {r['old_hours']:.0f}h -> {r['new_hours']:.0f}h."
            out.append(line)
        return "\n".join(out)
