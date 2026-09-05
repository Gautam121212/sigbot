"""Event memory — what happened last time, without choosing which times to keep.

Items 15–17 of the roadmap, built with two changes to the specification. Both
changes exist because the version as written would have manufactured the exact
bias this project spends its whole life preventing.

## Change 1: no admission filter

The proposal admits an event only if it moved the price more than 3%. Simulated
over 300 events with no genuine effect:

    events seen        300
    events admitted     76
    quiet ones dropped 224

Every base rate computed from that store is conditioned on having moved. "Tesla
launches move the stock 86% of the time" would be true of the database and false
of the world, because the quiet launches were never written down. **Every event
is stored here, moved or not.** A quiet outcome is evidence; discarding it is
how a precedent store lies.

## Change 2: no fabricated dates

The proposal defaults a year-only Wikipedia date to January 1st and then
measures the price reaction from there. An event from November gets scored
against the first trading days of January. Those rows are not noisy, they are
wrong, and they look identical to correct ones.

Here, `date_precision` is stored with every event and anything coarser than a
day is **excluded from base rates**. It stays in the store as context and is
never counted.

## What this can and cannot tell you

It answers: *of the recorded times something like this happened to this asset,
how often did the price go which way, and what is the interval around that?*

It cannot tell you the event caused the move. It cannot correct for the fact
that a headline you can retrieve today is not the headline set you would have
seen then. And with fewer than `MIN_PRECEDENTS` matches it says nothing at all,
because three coin flips are not a pattern.
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .providers.news import jaccard, tokens
from .stats import wilson_interval

MIN_PRECEDENTS = 5          # below this, no rate is reported at all
# On stemmed, stopword-stripped tokens. Calibrated against real pairs:
#
#   0.71  "Tesla unveils new Model Y refresh" / "...with longer range"   match
#   0.67  "Nvidia beats earnings estimates"   / "Nvidia earnings beat..."  match
#   0.29  "Tesla to unveil robotaxi next month" / "Tesla unveils product"  reject
#   0.11  "Tesla unveils Model Y" / "Tesla recalls vehicles"               reject
#
# The third is the honest cost: the same kind of event worded loosely is
# rejected. That is the right way to be wrong here. Pooling loosely-worded
# events inflates the precedent count with things that are not precedents, and
# an inflated count is what the Wilson bound is protecting you from. Raising
# the floor loses matches; lowering it invents them.
SIMILARITY_FLOOR = 0.45
RECENCY_HALFLIFE_DAYS = 900.0
MAX_PRECEDENTS = 25
STRONG_FLOOR = 0.60         # on the Wilson lower bound, never the observed rate
WEAK_FLOOR = 0.50

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id       TEXT PRIMARY KEY,
    asset          TEXT NOT NULL,
    event_date     TEXT NOT NULL,
    date_precision TEXT NOT NULL,   -- 'day' | 'month' | 'year'
    headline       TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    source         TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    return_1d      REAL,
    return_3d      REAL,
    return_5d      REAL,
    volume_z       REAL,
    -- 1 only when the return was measured from a day-precision date against
    -- bars that existed at the time. Everything else stays context.
    countable      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_ev_asset ON events(asset, event_type);
CREATE INDEX IF NOT EXISTS ix_ev_count ON events(countable);
"""


@dataclass(frozen=True)
class Event:
    asset: str
    event_date: str
    headline: str
    event_type: str
    source: str
    date_precision: str = "day"
    return_1d: float | None = None
    return_3d: float | None = None
    return_5d: float | None = None
    volume_z: float | None = None

    @property
    def event_id(self) -> str:
        raw = f"{self.asset}|{self.event_date}|{self.headline}|{self.source}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @property
    def countable(self) -> bool:
        """Only day-precision events with a measured return may enter a rate."""
        return self.date_precision == "day" and self.return_3d is not None


@dataclass
class Precedent:
    event: Event
    similarity: float
    age_days: int

    @property
    def weight(self) -> float:
        return self.similarity * 0.5 ** (self.age_days / RECENCY_HALFLIFE_DAYS)


@dataclass
class Recurrence:
    asset: str
    headline: str
    event_type: str
    n_precedents: int
    n_excluded: int
    up_rate: float | None
    lower: float | None
    upper: float | None
    median_3d: float | None
    similarity_range: tuple[float, float] | None
    dates: list[str] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.n_precedents < MIN_PRECEDENTS or self.lower is None:
            return "NO PATTERN"
        if self.lower >= STRONG_FLOOR:
            return "STRONG"
        if self.lower >= WEAK_FLOOR:
            return "WEAK"
        return "NO PATTERN"

    def render(self) -> str:
        head = f"{self.asset} — {self.headline[:70]}"
        if self.n_precedents < MIN_PRECEDENTS:
            extra = (f", {self.n_excluded} excluded for imprecise dates"
                     if self.n_excluded else "")
            return (f"{head}\n  NO PATTERN — {self.n_precedents} usable precedent(s)"
                    f"{extra}. Below {MIN_PRECEDENTS}, nothing is reported.")
        lo, hi = self.similarity_range or (0, 0)
        lines = [
            head,
            f"  {self.verdict} — {self.n_precedents} similar events "
            f"(similarity {lo:.2f}\u2013{hi:.2f})",
            f"  went up {self.up_rate:.0%} of the time; "
            f"90% interval {self.lower:.0%}\u2013{self.upper:.0%}",
            f"  median 3-day move {self.median_3d:+.1%}",
            "  dates: " + ", ".join(self.dates[:8]),
        ]
        if self.n_excluded:
            lines.append(f"  {self.n_excluded} further event(s) excluded: the date "
                         "was only known to the month or year, so the price "
                         "reaction cannot be attributed to them.")
        lines.append("  This is the recorded base rate of similar past events. "
                     "It is not a forecast, and it does not show the event "
                     "caused the move.")
        return "\n".join(lines)


class EventMemory:
    def __init__(self, path: str | Path = "event_memory.db"):
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
    def record(self, event: Event) -> bool:
        """Store an event. Returns False if it was already there.

        No admission filter. A launch that moved nothing is exactly as much
        evidence as one that moved 8%, and keeping only the second is how the
        store ends up claiming everything moves.
        """
        with closing(sqlite3.connect(self.path)) as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO events(event_id,asset,event_date,"
                "date_precision,headline,event_type,source,recorded_at,"
                "return_1d,return_3d,return_5d,volume_z,countable) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event.event_id, event.asset, event.event_date,
                 event.date_precision, event.headline, event.event_type,
                 event.source, datetime.now(timezone.utc).isoformat(),
                 event.return_1d, event.return_3d, event.return_5d,
                 event.volume_z, int(event.countable)))
            con.commit()
            return cur.rowcount > 0

    def count(self, asset: str | None = None, countable_only: bool = False) -> int:
        q = "SELECT COUNT(*) FROM events WHERE 1=1"
        args: list = []
        if asset:
            q += " AND asset=?"
            args.append(asset)
        if countable_only:
            q += " AND countable=1"
        with closing(sqlite3.connect(self.path)) as con:
            return int(con.execute(q, args).fetchone()[0])

    _COLS = ("asset", "event_date", "headline", "event_type", "source",
             "date_precision", "return_1d", "return_3d", "return_5d", "volume_z")

    def _events_for(self, asset: str, event_type: str | None) -> list[Event]:
        q = ("SELECT asset,event_date,headline,event_type,source,date_precision,"
             "return_1d,return_3d,return_5d,volume_z FROM events WHERE asset=?")
        args: list = [asset]
        if event_type:
            q += " AND event_type=?"
            args.append(event_type)
        with closing(sqlite3.connect(self.path)) as con:
            return [Event(*row) for row in con.execute(q, args)]

    # ------------------------------------------------------------ matching
    def precedents(self, asset: str, headline: str, event_type: str | None = None,
                   on: datetime | None = None) -> list[Precedent]:
        """Similar past events for this asset, most relevant first.

        Similarity runs on the stemmed, stopword-stripped tokens already used
        for news deduplication, so "Tesla launches car" and "Tesla recalls car"
        do not read as the same event.
        """
        now = on or datetime.now(timezone.utc)
        target = tokens(headline)
        out: list[Precedent] = []
        for ev in self._events_for(asset, event_type):
            sim = jaccard(target, tokens(ev.headline))
            if sim < SIMILARITY_FLOOR:
                continue
            try:
                age = (now - datetime.fromisoformat(ev.event_date).replace(
                    tzinfo=timezone.utc)).days
            except ValueError:
                continue
            if age < 0:
                continue          # a future-dated row is bad data, not a precedent
            out.append(Precedent(ev, sim, age))
        out.sort(key=lambda p: -p.weight)
        return out[:MAX_PRECEDENTS]

    # ------------------------------------------------------------- scoring
    def recurrence(self, asset: str, headline: str, event_type: str | None = None,
                   on: datetime | None = None) -> Recurrence:
        """Base rate over matching precedents, with its interval.

        The verdict reads the **lower** bound, never the observed rate. Six of
        seven is 86% and a lower bound of 47%, and reporting the first without
        the second is the whole problem.
        """
        found = self.precedents(asset, headline, event_type, on)
        usable = [p for p in found if p.event.countable]
        excluded = len(found) - len(usable)

        if len(usable) < MIN_PRECEDENTS:
            return Recurrence(asset, headline, event_type or "any", len(usable),
                              excluded, None, None, None, None, None)

        # `countable` already guarantees return_3d is present, but say so here:
        # relying on an invariant enforced somewhere else is how a None reaches
        # arithmetic six months later.
        rets = [p.event.return_3d for p in usable if p.event.return_3d is not None]
        if len(rets) < MIN_PRECEDENTS:
            return Recurrence(asset, headline, event_type or "any", len(rets),
                              excluded + (len(usable) - len(rets)),
                              None, None, None, None, None)
        ups = sum(1 for r in rets if r > 0)
        lo, hi = wilson_interval(ups, len(rets), 0.90)
        sims = [p.similarity for p in usable]
        ordered = sorted(rets)
        mid = len(ordered) // 2
        median = (ordered[mid] if len(ordered) % 2
                  else (ordered[mid - 1] + ordered[mid]) / 2)

        return Recurrence(
            asset=asset, headline=headline, event_type=event_type or "any",
            n_precedents=len(usable), n_excluded=excluded,
            up_rate=ups / len(rets), lower=lo, upper=hi, median_3d=median,
            similarity_range=(min(sims), max(sims)),
            dates=[p.event.event_date for p in usable],
            returns=[round(r, 4) for r in rets])

    def eligible_assets(self, frames: dict) -> list[str]:
        """Assets with enough history for this store to say anything.

        Pointing the scanner at a name listed last year burns a slot that a
        twenty-year name would fill, and produces "NO PATTERN" forever without
        ever explaining that history, not the asset, is the reason.
        """
        from .history import precedent_universe

        return precedent_universe(frames)

    def summary(self) -> str:
        total, countable = self.count(), self.count(countable_only=True)
        if not total:
            return ("Event memory is empty. It fills as news arrives and the "
                    "price reaction is measured 3 days later — nothing can be "
                    "reported until then.")
        return (f"{total} events recorded, {countable} countable "
                f"({total - countable} excluded for imprecise dates or missing "
                f"returns). A pattern needs {MIN_PRECEDENTS} matching precedents.")
