"""What the model thinks today — as a claim, next to what it has earned.

The Board colours by record, which needs 100+ resolved checks per asset. For
the first several months that means the same amber every day and no way to see
the daily output at all. That is a real gap: you cannot watch a system work if
it only speaks once it is certain.

## Two colours that must never merge

    claim     the model's stated probability, today, before anything is checked
    record    how often it has actually been right, measured

A 72% claim shows green-as-claimed with "0 checks behind it" printed beside it.
Both facts, side by side, neither wearing the other's authority.

The temptation is to colour a 72% call green and leave it there. Your own
contagion run is the argument against: links at t = -9 and q = 0.000 — far more
confident than 72% — and zero of 353 cleared the gates once measured. A stated
number and a demonstrated one are different quantities, and the distance
between them is where trading systems die.

Honest constraint: the bands below are the model's own signal thresholds, not
evidence that 65% is a meaningful line. Until a few hundred forecasts resolve,
nobody knows whether this model's 70% means 70%, 50%, or 40%. `progress.py`
answers that with the Brier score, and it answers it long before any tier does.

Largest risk: that a screen of green claims reads as a screen of opportunities.
Every card carries its check count for that reason, and a claim with no record
behind it says so in words rather than only in a number.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

GREEN, AMBER, RED, GREY = "#00e676", "#ffd93d", "#ff5c5c", "#8b8b9a"

# The model's own signal thresholds. Not evidence that these are the right
# lines — evidence would require resolved forecasts, which is what the record
# column is for.
STRONG = 0.65
WEAK = 0.50

# Below this many resolved checks, the asset's own record cannot say anything.
RECORD_FLOOR = 25


@dataclass
class Call:
    symbol: str
    side: str
    score: float
    expected_move: float
    colour: str
    claim: str
    checks: int
    hits: int
    record: str
    alerted: bool = False


@dataclass
class Today:
    calls: list[Call] = field(default_factory=list)
    made: int = 0
    open_now: int = 0
    waiting: int = 0
    note: str = ""


def _band(score: float, side: str) -> tuple[str, str]:
    """Colour for the claim alone. Says 'claims', never 'is'."""
    if side.upper() == "HOLD":
        return GREY, "no call — the model sees nothing either way"
    if score >= STRONG:
        return GREEN, f"claims {score:.0%} — its own bar for a signal is {STRONG:.0%}"
    if score >= WEAK:
        return AMBER, f"claims {score:.0%} — leaning, below its signal bar"
    return RED, f"claims {score:.0%} — leaning against"


def _record(checks: int, hits: int) -> str:
    if checks == 0:
        return "no checks behind it yet, so this claim is untested"
    if checks < RECORD_FLOOR:
        return (f"{hits}/{checks} right so far — far too few to mean anything, "
                "and shown only so it is not hidden")
    from .stats import wilson_interval

    low, _high = wilson_interval(hits, checks, 0.90)
    return f"{hits}/{checks} right, worst case {low:.0%} over {checks} checks"


def read(db_path: str, hours: int = 26, limit: int = 40) -> Today:
    """Today's forecasts, strongest claim first."""
    out = Today()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    try:
        with sqlite3.connect(db_path) as con:
            rows = con.execute(
                # Only what is still open. Including resolved rows meant an
                # asset's own history reappeared as a dozen duplicate "calls",
                # which is worse than showing nothing: it manufactures the
                # appearance of many opportunities from one.
                "SELECT symbol, side, score, expected_move, alerted "
                "FROM predictions WHERE created_at >= ? AND score IS NOT NULL "
                "AND hit IS NULL ORDER BY score DESC LIMIT ?",
                (since, limit)).fetchall()
            out.made = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE created_at >= ?",
                (since,)).fetchone()[0]
            out.open_now = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE created_at >= ? "
                "AND hit IS NULL", (since,)).fetchone()[0]
            out.waiting = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE hit IS NULL").fetchone()[0]

            # Latest call per symbol. Running `runner daily` by hand while the
            # scheduler also runs it is legitimate; showing the same asset
            # twice as two separate opportunities is not.
            seen: set[str] = set()
            for symbol, side, score, move, alerted in rows:
                if symbol in seen:
                    continue
                seen.add(symbol)
                checks, hits = con.execute(
                    "SELECT COUNT(hit), COALESCE(SUM(hit),0) FROM predictions "
                    "WHERE symbol=? AND hit IS NOT NULL", (symbol,)).fetchone()
                colour, claim = _band(float(score), side or "HOLD")
                out.calls.append(Call(
                    symbol, side or "HOLD", float(score), float(move or 0.0),
                    colour, claim, checks, hits, _record(checks, hits),
                    bool(alerted)))
    except sqlite3.Error as exc:
        out.note = (f"The ledger could not be read ({exc}). Nothing below is "
                    "trustworthy until that is fixed.")
        return out

    if not out.calls:
        # Nothing open is not the same as nothing made. An earlier version
        # reported a fault whenever the list was empty, which is exactly what
        # a healthy day looks like once every forecast has been scored and
        # before the next run has fired.
        if out.made:
            out.note = (f"Nothing open. All {out.made} forecast(s) from the "
                        "last day have been scored, and the next daily run "
                        "has not fired yet — which is what a working day looks "
                        "like between runs, not a fault.")
        else:
            out.note = ("No forecasts recorded in the last day at all. Either "
                        "the daily job has not run, or it ran and recorded "
                        "nothing — both are faults, and neither is a market "
                        "observation.")
    return out


def render(today: Today) -> str:
    if today.note and not today.calls:
        return today.note

    lines = [f"Today's calls — {today.open_now} open, {today.waiting} waiting "
             f"to be scored ({today.made} recorded in the window)", ""]
    live = [c for c in today.calls if c.side.upper() != "HOLD"]
    if not live:
        lines.append("Every asset came back HOLD. The model scored all of them "
                     "and none crossed its own signal bar. That is the usual "
                     "outcome, and each hold is still recorded and still "
                     "scored tomorrow — a hold that would have risen is a data "
                     "point too.")
    for call in live[:12]:
        lines.append(f"{call.symbol} {call.side} — {call.claim}")
        lines.append(f"    expected {call.expected_move:+.2%} · {call.record}")
    lines += ["",
              "The colour above is the model's claim, not its record. Nothing "
              "here has been checked yet; whether this model's 70% means 70% "
              "is what `python -m sigbot.progress` answers, and it can answer "
              "it long before any asset earns a tier."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .config import SETTINGS

    ap = argparse.ArgumentParser(description="What the model thinks today.")
    ap.add_argument("--db", default=SETTINGS.shadow_db)
    ap.add_argument("--hours", type=int, default=26)
    args = ap.parse_args(argv)

    print(render(read(args.db, args.hours)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
