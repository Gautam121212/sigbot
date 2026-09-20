"""Pattern registry: discovery, pruning, and out-of-sample confirmation.

The strategy this implements — test many patterns, prune the failures, keep the
survivors — is sound. But run naively it produces an estimate that is wrong in a
specific and predictable direction, and the whole point of the tier system is to
not lie about the number.

## The selection problem, measured

Simulating 400 patterns per campaign through prune-at-20 and promote-at-100
with a 0.65 Wilson floor, 40 campaigns each:

    population                          promoted/campaign  reported  true    bias
    400 pure noise (true 50%)                        0.0       —      —       —
    380 noise + 20 real (true 62%)                   0.8    72.5%  62.0%  +10.5pp
    380 noise + 20 strong (true 70%)                14.8    73.1%  70.0%   +3.1pp

Two things follow.

The 0.65 floor genuinely works: across 16,000 pure-noise pattern-runs, not one
reached TRADE. False discovery is not the failure mode here.

The failure mode is the *reported number*. A population whose true rate is 62%
gets promoted showing 72.5%, because a pattern only crosses the floor on a run
of luck and the statistic is measured on the same data that selected it. "70%
accuracy" is exactly what a 62% system looks like from the inside.

## The fix

Two stages, with a hard reset between them.

    DISCOVERY   — accumulate, prune the obvious failures, and when the floor is
                  crossed, promote to CONFIRMING and **zero the counters**.
    CONFIRMING  — accumulate a fresh sample the pattern was not selected on.
                  Only this sample is quoted as the pattern's hit rate.
    CONFIRMED   — cleared both. The confirmation statistic is unconditioned and
                  therefore honest.

Confirmation gate chosen by simulation rather than picked (pass rates at 90%
confidence, n>=60, lower>=0.50):

    true 50% -> 4.4%    true 55% -> 18.4%    true 62% -> 58.1%    true 70% -> 93.6%

That rejects noise hard, passes genuinely strong patterns nearly always, and is
reachable — a stricter gate would leave real patterns stuck in CONFIRMING
forever, which is its own kind of dishonesty.

One caveat, stated because it would otherwise be a hidden overclaim: the
confirmation *gate* is itself a filter, so restricting attention to CONFIRMED
patterns reintroduces a small upward conditioning. The fully unbiased quantity
is the confirmation-sample rate across every promoted pattern, which is what
`test_confirmation_sample_is_an_unbiased_estimate` measures. Discovery bias of
+10pp becomes roughly +1-2pp, not zero.

## What this floor costs

A true 62% edge is real and worth trading, and this pipeline discards it most
of the time — a 0.65 discovery floor needs ~74% observed at n=100. That is a
deliberate trade: false confidence costs more than a missed pattern. But it
means "3-5 patterns at 65-75%" requires patterns whose TRUE rate is near 70%,
not 62%.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .stats import wilson_interval


class Stage(str, Enum):
    DISCOVERY = "DISCOVERY"
    CONFIRMING = "CONFIRMING"
    CONFIRMED = "CONFIRMED"
    PRUNED = "PRUNED"


@dataclass(frozen=True)
class RegistryRules:
    prune_after_n: int = 20
    prune_below_rate: float = 0.45
    discovery_n: int = 100
    discovery_lower: float = 0.65
    confirm_n: int = 60
    confirm_lower: float = 0.50
    conf: float = 0.90


RULES = RegistryRules()

SCHEMA = """
CREATE TABLE IF NOT EXISTS patterns (
    pattern_key   TEXT PRIMARY KEY,
    model         TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    stage         TEXT NOT NULL,
    disc_n        INTEGER NOT NULL DEFAULT 0,
    disc_hits     INTEGER NOT NULL DEFAULT 0,
    conf_n        INTEGER NOT NULL DEFAULT 0,
    conf_hits     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    promoted_at   TEXT,
    pruned_at     TEXT
);
-- Idempotency. A collector that re-reads the last N shocks on every cron run
-- would otherwise record the same observation several times a day and inflate
-- exactly the sample size that gates promotion.
CREATE TABLE IF NOT EXISTS observations (
    pattern_key   TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    hit           INTEGER NOT NULL,
    stage         TEXT NOT NULL,
    recorded_at   TEXT NOT NULL,
    PRIMARY KEY (pattern_key, observation_id)
);
"""


@dataclass
class PatternRecord:
    pattern_key: str
    model: str
    symbol: str
    stage: Stage
    disc_n: int
    disc_hits: int
    conf_n: int
    conf_hits: int

    @property
    def quoted_n(self) -> int:
        """Only the confirmation sample may be quoted once a pattern is past discovery."""
        return self.conf_n if self.stage in (Stage.CONFIRMING, Stage.CONFIRMED) else self.disc_n

    @property
    def quoted_hits(self) -> int:
        return self.conf_hits if self.stage in (Stage.CONFIRMING, Stage.CONFIRMED) else self.disc_hits

    @property
    def hit_rate(self) -> float:
        return self.quoted_hits / self.quoted_n if self.quoted_n else float("nan")

    @property
    def lower_bound(self) -> float:
        return wilson_interval(self.quoted_hits, self.quoted_n, RULES.conf)[0]

    @property
    def alertable(self) -> bool:
        return self.stage is Stage.CONFIRMED

    def render(self) -> str:
        note = {
            Stage.DISCOVERY: "discovery sample — selected on this data, so the rate is optimistic",
            Stage.CONFIRMING: "fresh sample since promotion — not yet enough to confirm",
            Stage.CONFIRMED: ("out-of-sample since promotion — unconditioned with respect "
                              "to discovery, though the confirmation gate is itself a mild filter"),
            Stage.PRUNED: "dropped",
        }[self.stage]
        if self.quoted_n == 0:
            return f"{self.pattern_key} [{self.stage.value}] — no observations yet ({note})"
        return (
            f"{self.pattern_key} [{self.stage.value}] "
            f"{self.quoted_n} obs, {self.hit_rate:.1%}, "
            f"90% lower bound {self.lower_bound:.1%}\n    {note}"
        )


class PatternRegistry:
    def __init__(self, path: str | Path = "patterns.db", rules: RegistryRules = RULES):
        self.path = str(path)
        self.rules = rules
        # One long-lived connection. Opening one per write cost ~5ms each, which
        # is invisible at cron frequency and crippling in a simulation loop.
        self._con = sqlite3.connect(self.path, check_same_thread=False)
        # WAL, as in the other stores. This one keeps a persistent connection
        # rather than opening per call, which is why a pattern-match on
        # `con.executescript` missed it — a reminder that a codemod finds the
        # shape it was written for, not the intent.
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(SCHEMA)
        self._con.commit()

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "PatternRegistry":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- write
    def record(self, pattern_key: str, model: str, symbol: str,
               observation_id: str, hit: bool) -> Stage:
        """Record one resolved observation. Idempotent on `observation_id`.

        `observation_id` must identify the underlying event, not the moment the
        collector ran — a bar timestamp, not `datetime.now()`. Re-running the
        collector then costs nothing instead of manufacturing evidence.
        """
        now = datetime.now(timezone.utc).isoformat()
        r = self.rules
        con = self._con
        if True:
            con.execute(
                "INSERT OR IGNORE INTO patterns(pattern_key,model,symbol,stage,created_at) "
                "VALUES (?,?,?,?,?)",
                (pattern_key, model, symbol, Stage.DISCOVERY.value, now),
            )
            row = con.execute(
                "SELECT stage,disc_n,disc_hits,conf_n,conf_hits FROM patterns "
                "WHERE pattern_key=?", (pattern_key,)
            ).fetchone()
            stage = Stage(row[0])
            if stage is Stage.PRUNED:
                return stage

            cur = con.execute(
                "INSERT OR IGNORE INTO observations"
                "(pattern_key,observation_id,hit,stage,recorded_at) VALUES (?,?,?,?,?)",
                (pattern_key, observation_id, int(bool(hit)), stage.value, now),
            )
            if cur.rowcount == 0:
                return stage  # already seen; nothing changes

            disc_n, disc_hits, conf_n, conf_hits = row[1], row[2], row[3], row[4]
            if stage is Stage.DISCOVERY:
                disc_n += 1
                disc_hits += int(bool(hit))
            else:
                conf_n += 1
                conf_hits += int(bool(hit))

            new_stage: Stage = stage
            promoted_at: str | None = None
            pruned_at: str | None = None

            if stage is Stage.DISCOVERY:
                if disc_n >= r.prune_after_n and disc_hits / disc_n < r.prune_below_rate:
                    new_stage, pruned_at = Stage.PRUNED, now
                elif (disc_n >= r.discovery_n
                      and wilson_interval(disc_hits, disc_n, r.conf)[0] >= r.discovery_lower):
                    # Promote AND reset. The discovery statistic selected this
                    # pattern, so it cannot also be the evidence for it.
                    new_stage, promoted_at = Stage.CONFIRMING, now
                    conf_n = conf_hits = 0
            elif stage is Stage.CONFIRMING:
                if (conf_n >= r.confirm_n
                        and wilson_interval(conf_hits, conf_n, r.conf)[0] >= r.confirm_lower):
                    new_stage = Stage.CONFIRMED
                elif conf_n >= r.prune_after_n and conf_hits / conf_n < r.prune_below_rate:
                    new_stage, pruned_at = Stage.PRUNED, now

            con.execute(
                "UPDATE patterns SET stage=?,disc_n=?,disc_hits=?,conf_n=?,conf_hits=?,"
                "promoted_at=COALESCE(?,promoted_at),pruned_at=COALESCE(?,pruned_at) "
                "WHERE pattern_key=?",
                (new_stage.value, disc_n, disc_hits, conf_n, conf_hits,
                 promoted_at, pruned_at, pattern_key),
            )
            con.commit()
            return new_stage

    # ----------------------------------------------------------------- read
    def get(self, pattern_key: str) -> PatternRecord | None:
        row = self._con.execute(
            "SELECT pattern_key,model,symbol,stage,disc_n,disc_hits,conf_n,conf_hits "
            "FROM patterns WHERE pattern_key=?", (pattern_key,)
        ).fetchone()
        return PatternRecord(row[0], row[1], row[2], Stage(row[3]), *row[4:]) if row else None

    def by_stage(self, stage: Stage) -> list[PatternRecord]:
        rows = self._con.execute(
            "SELECT pattern_key,model,symbol,stage,disc_n,disc_hits,conf_n,conf_hits "
            "FROM patterns WHERE stage=? ORDER BY conf_n DESC, disc_n DESC",
            (stage.value,),
        ).fetchall()
        return [PatternRecord(r[0], r[1], r[2], Stage(r[3]), *r[4:]) for r in rows]

    def alertable(self) -> list[PatternRecord]:
        return self.by_stage(Stage.CONFIRMED)

    def summary(self) -> str:
        counts = {s: len(self.by_stage(s)) for s in Stage}
        lines = [
            "Pattern registry: "
            + ", ".join(f"{s.value.lower()} {counts[s]}" for s in Stage),
        ]
        if counts[Stage.CONFIRMED] == 0:
            lines.append(
                "No pattern has cleared out-of-sample confirmation. Nothing is alertable."
            )
        for rec in self.alertable()[:5] + self.by_stage(Stage.CONFIRMING)[:5]:
            lines.append("  " + rec.render())
        return "\n".join(lines)
