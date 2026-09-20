"""The rolling 100 — selection, colour flags, and rotation.

## What I cannot do, stated first

You asked me to run my outcomes and pick the 100 that perform. I cannot, for two
reasons worth being blunt about.

My knowledge has a cutoff and today is past it, so I am not current on the news
you want the selection to reflect. More importantly, **the ledger is empty**. If
I picked 100 names today and called it performance-based, that would be me
choosing from priors and dressing it as measurement — the exact move this
project has spent its whole life removing. A ranked list of "the best 100" built
before any outcome exists is a horoscope with tickers.

So selection splits in two, and only the second half is ever mine to make.

**Entry is structural.** An asset joins the list on things true today and
checkable by anyone: it trades enough to get in and out of, it is covered enough
to generate news, and it is not a duplicate of something already on the list.
None of that is a prediction.

**Exit is measured.** An asset leaves on its own record, once that record is
thick enough to mean something. Nothing leaves on my opinion of it.

## The asymmetry that keeps rotation honest

Promote on the **lower** bound, demote on the **upper** bound.

Keeping the winners and dropping the losers on short-run results is a machine
for manufacturing survivorship bias — the surviving list looks excellent because
the failures were removed, and the record you quote is the record of a selection
process, not of a strategy. Earlier in this project that effect measured +10
points.

The defence is to make demotion hard in exactly the way promotion is hard.
Dropping happens only when even the *most flattering* reading of the record
fails:

    n=20  at 45% observed -> upper bound 63%   keep
    n=40  at 45% observed -> upper bound 58%   keep
    n=100 at 45% observed -> upper bound 53%   keep
    n=200 at 45% observed -> upper bound 51%   DROP
    n=100 at 40% observed -> upper bound 48%   DROP

A genuinely useful asset reads 45% over twenty checks often enough that dropping
on it is firing someone for a bad fortnight. By two hundred checks it is real.

## Colours

    GREEN   the record clears the bar at 90% confidence — worth acting on
    AMBER   either too early to say, or measurable but weak — watch, do not act
    RED     even the optimistic reading fails — scheduled to be replaced

Most of the list is amber for months. That is what an honest board looks like
before the evidence arrives, and a board that went green early would be lying.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .stats import wilson_interval

TARGET_SIZE = 100


class Flag(str, Enum):
    # Unmeasured. Distinct from AMBER, which is a verdict: "risky" on zero
    # checks states a conclusion about evidence that does not exist, and a
    # hundred assets labelled risky on their first day is a hundred false
    # claims.
    TESTING = "TESTING"
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"

    @property
    def label(self) -> str:
        return {Flag.TESTING: "Being tested",
                Flag.GREEN: "Ready to trade",
                Flag.AMBER: "Risky — watch only",
                Flag.RED: "Do not trade"}[self]

    @property
    def colour(self) -> str:
        return {Flag.TESTING: "#8b8b9a", Flag.GREEN: "#00e676",
                Flag.AMBER: "#ffd93d", Flag.RED: "#ff6b6b"}[self]


@dataclass(frozen=True)
class Rules:
    green_min_n: int = 60          # below this, no record is thick enough to trust
    green_min_lower: float = 0.55  # the lower bound must clear this
    amber_min_n: int = 25
    amber_min_lower: float = 0.50
    drop_min_n: int = 100          # never drop on a thin sample
    drop_max_upper: float = 0.52   # drop only if even the best reading fails
    cooldown_days: int = 90        # a dropped name cannot return before this
    max_drops_per_cycle: int = 2   # one or two at a time. A board that turns
                                   # over in bulk is fitting noise, and it also
                                   # destroys the like-for-like comparison
                                   # between incumbents and newcomers
    conf: float = 0.90


RULES = Rules()

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol     TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    added_at   TEXT NOT NULL,
    reason     TEXT
);
CREATE TABLE IF NOT EXISTS graveyard (
    symbol     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    dropped_at TEXT NOT NULL,
    n          INTEGER,
    rate       REAL,
    upper      REAL,
    reason     TEXT,
    PRIMARY KEY (symbol, dropped_at)
);
"""


@dataclass
class Slot:
    symbol: str
    kind: str
    description: str
    n: int
    rate: float | None
    lower: float | None
    upper: float | None
    flag: Flag
    reason: str

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["kind"] = self.kind
        d["flag"] = self.flag.value
        d["flag_label"] = self.flag.label
        d["colour"] = self.flag.colour
        return d


# Two gates, not one. Admission asks whether an asset has been checked enough
# to be worth a line on the board at all; colour asks what those checks say.
#
# Conflating them is why the board reads as a hundred amber tiles that say the
# same thing for months: everything is shown, and everything is amber, so the
# display carries no information. Separating them means the board shows what
# has been measured and the rest waits in Learned and Missed, which is where
# an unmeasured asset belongs.
ADMISSION_CHECKS = 25


def admitted(n: int, rules: Rules = RULES) -> bool:
    """Whether this asset has enough checks for its colour to mean anything."""
    return n >= max(ADMISSION_CHECKS, rules.amber_min_n)


def waiting_note(n: int, rules: Rules = RULES) -> str:
    """What to say about an asset that has not been admitted yet."""
    need = max(ADMISSION_CHECKS, rules.amber_min_n)
    short = need - n
    return (f"{n} of {need} checks. Not shown on the board until there is "
            f"enough to colour honestly — about {short} more trading day(s). "
            "Its forecasts are still being made and scored; they appear in "
            "Learned and Missed as they resolve.")


def classify(n: int, hits: float, rules: Rules = RULES) -> tuple[Flag, str]:
    """Colour from the record alone. Never from an opinion about the asset."""
    if n < rules.amber_min_n:
        # Not a verdict. "Risky" on zero checks states a conclusion about
        # evidence that does not exist, and a hundred assets labelled risky on
        # their first day is a hundred false claims.
        need = max(ADMISSION_CHECKS, rules.amber_min_n)
        return Flag.TESTING, (
            f"{n} of {need} checks. Forecast and scored every day; the colour "
            f"arrives once there is enough to earn one — about {need - n} more "
            "trading day(s).")
    if False:
        # Say how far off it is, not only that it is not there. "Needs 25" with
        # no sense of the rate leaves you unable to tell a board that is
        # filling from one that has stopped.
        short = rules.amber_min_n - n
        return Flag.AMBER, (f"{n} of {rules.amber_min_n} checks. {short} more "
                            "before the colour means anything — about "
                            f"{short} more trading day(s), one check a day.")
    lower, upper = wilson_interval(hits, n, rules.conf)
    rate = hits / n

    if n >= rules.drop_min_n and upper < rules.drop_max_upper:
        return Flag.RED, (f"Right {rate:.0%} of {n} checks. Even the most flattering "
                          f"reading of that record ({upper:.0%}) loses to a coin flip. "
                          "Scheduled for replacement.")
    if n >= rules.green_min_n and lower >= rules.green_min_lower:
        return Flag.GREEN, (f"Right {rate:.0%} of {n} checks. Worst case {lower:.0%}, "
                            f"which clears {rules.green_min_lower:.0%}.")
    if lower >= rules.amber_min_lower:
        return Flag.AMBER, (f"Right {rate:.0%} of {n} checks. Worst case {lower:.0%} — "
                            "better than a coin, not by enough to act on.")
    return Flag.AMBER, (f"Right {rate:.0%} of {n} checks. Worst case {lower:.0%}, "
                        "which does not beat a coin flip yet. Still collecting.")


class Watchlist:
    """The live 100, plus everything that has been dropped and why."""

    def __init__(self, path: str | Path = "watchlist.db", rules: Rules = RULES):
        self.path = str(path)
        self.rules = rules
        with closing(sqlite3.connect(self.path)) as con:
            # WAL lets readers work while a writer holds the file. Without it
            # a system polling several markets at once eventually returns
            # "database is locked", which surfaces as a data outage rather than
            # as the contention it actually is. Persistent once set, so this is
            # a one-time property of the file, not a per-connection setting.
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            con.commit()

    # ------------------------------------------------------------- members
    def symbols(self) -> list[str]:
        with closing(sqlite3.connect(self.path)) as con:
            return [r[0] for r in con.execute(
                "SELECT symbol FROM watchlist ORDER BY added_at, symbol")]

    def add(self, symbol: str, kind: str, reason: str = "structural") -> bool:
        """Add unless it is already present or inside its cooldown."""
        now = datetime.now(timezone.utc)
        with closing(sqlite3.connect(self.path)) as con:
            if con.execute("SELECT 1 FROM watchlist WHERE symbol=?", (symbol,)).fetchone():
                return False
            row = con.execute(
                "SELECT dropped_at FROM graveyard WHERE symbol=? ORDER BY dropped_at DESC",
                (symbol,)).fetchone()
            if row:
                dropped = datetime.fromisoformat(row[0])
                if (now - dropped).days < self.rules.cooldown_days:
                    return False   # re-adding a fresh failure is chasing noise
            con.execute("INSERT INTO watchlist(symbol,kind,added_at,reason) VALUES (?,?,?,?)",
                        (symbol, kind, now.isoformat(), reason))
            con.commit()
            return True

    def drop(self, symbol: str, n: int, rate: float | None,
             upper: float | None, reason: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute("SELECT kind FROM watchlist WHERE symbol=?", (symbol,)).fetchone()
            if not row:
                return
            con.execute("INSERT OR REPLACE INTO graveyard"
                        "(symbol,kind,dropped_at,n,rate,upper,reason) VALUES (?,?,?,?,?,?,?)",
                        (symbol, row[0], now, n, rate, upper, reason))
            con.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
            con.commit()

    def graveyard(self, limit: int = 50) -> list[dict]:
        cols = ("symbol", "kind", "dropped_at", "n", "rate", "upper", "reason")
        with closing(sqlite3.connect(self.path)) as con:
            return [dict(zip(cols, r)) for r in con.execute(
                "SELECT symbol,kind,dropped_at,n,rate,upper,reason FROM graveyard "
                "ORDER BY dropped_at DESC LIMIT ?", (limit,))]

    # ---------------------------------------------------------------- seed
    def seed(self, candidates, target: int = TARGET_SIZE) -> int:
        """Fill to `target` from a ranked candidate list, keeping the mix balanced.

        `candidates` should arrive already ordered by `screen.screen_pool`, so
        the best-measured assets take the open slots. Interleaving by kind stops
        the board becoming all crypto simply because crypto screened highest as
        a group — one asset class owning every slot is a concentration risk the
        ranking alone will not catch.
        """
        by_kind: dict[str, list] = {}
        for a in candidates:
            by_kind.setdefault(a.kind, []).append(a)

        added, exhausted = 0, False
        while len(self.symbols()) < target and not exhausted:
            exhausted = True
            for kind in sorted(by_kind):
                if len(self.symbols()) >= target:
                    break
                while by_kind[kind]:
                    a = by_kind[kind].pop(0)
                    exhausted = False
                    if self.add(a.symbol, a.kind, "structural: liquid and covered"):
                        added += 1
                        break
        return added

    # -------------------------------------------------------------- review
    def review(self, records: dict[str, tuple[int, float]],
               descriptions: dict[str, str] | None = None) -> list[Slot]:
        """Colour every member from its record. `records` maps symbol -> (n, hits)."""
        descriptions = descriptions or {}
        out = []
        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute("SELECT symbol,kind FROM watchlist").fetchall()
        for symbol, kind in rows:
            n, hits = records.get(symbol, (0, 0.0))
            flag, reason = classify(n, hits, self.rules)
            lower, upper = (wilson_interval(hits, n, self.rules.conf) if n else (None, None))
            out.append(Slot(symbol, kind, descriptions.get(symbol, ""), n,
                            (hits / n) if n else None, lower, upper, flag, reason))
        # Problems first — that was the original intent and it is right: an
        # asset queued for replacement is the one needing attention. Then the
        # verdicts, and last everything still being tested, because an untested
        # asset is not a verdict and should not sit above one.
        order = {Flag.RED: 0, Flag.GREEN: 1, Flag.AMBER: 2, Flag.TESTING: 3}
        return sorted(out, key=lambda s: (order[s.flag], -s.n, s.symbol))

    def rotate(self, records: dict[str, tuple[int, float]], candidates,
               descriptions: dict[str, str] | None = None) -> dict:
        """Drop the worst reds, backfill from the ranked candidates.

        At most `max_drops_per_cycle` leave at a time, worst first. Replacing the
        whole board at once would mean every slot changed together, and nothing
        could then be compared against what it replaced.

        `candidates` must be freshly ranked each cycle, so an incumbent and a
        newcomer are judged on the same measurements taken at the same moment.
        """
        slots = self.review(records, descriptions)
        # Worst first: lowest upper bound is the most clearly finished.
        reds = sorted((s for s in slots if s.flag is Flag.RED),
                      key=lambda s: (s.upper if s.upper is not None else 1.0)
                      )[: self.rules.max_drops_per_cycle]
        for s in reds:
            self.drop(s.symbol, s.n, s.rate, s.upper, s.reason)

        held = set(self.symbols())
        pool = [a for a in candidates if a.symbol not in held]
        added = self.seed(pool)

        return {
            "dropped": [{"symbol": s.symbol, "n": s.n, "rate": s.rate,
                         "upper": s.upper, "reason": s.reason} for s in reds],
            "added": added,
            "size": len(self.symbols()),
            "note": (
                "Dropping the weak and keeping the strong is how survivorship bias "
                "gets built on purpose. The record of what remains is partly a record "
                "of this filter, not only of the assets — which is why every drop is "
                "kept in the graveyard with its numbers, why nothing is dropped "
                f"before {self.rules.drop_min_n} checks, and why only "
                f"{self.rules.max_drops_per_cycle} leave per cycle."
            ),
        }

    def summary(self, records: dict[str, tuple[int, float]]) -> str:
        slots = self.review(records)
        counts = {f: sum(1 for s in slots if s.flag is f) for f in Flag}
        lines = [f"Watchlist: {len(slots)} assets — "
                 + ", ".join(f"{counts[f]} {f.value.lower()}" for f in Flag)]
        if counts[Flag.GREEN] == 0:
            lines.append("Nothing is green yet. Early on that is correct: a board that "
                         "went green before the checks arrived would be guessing.")
        return "\n".join(lines)
