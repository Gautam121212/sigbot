"""Is it getting anywhere — measured, not asserted.

The Board answers "does anything clear the bar", and for months the answer is
no. That is correct and it is also unreadable: a screen that says the same thing
every day for a season gives you no way to tell a system that is accumulating
evidence from one that is quietly broken.

This answers a different question. Not "is there an edge" but "is the ledger
filling, and is the model honest about what it does not know". Both are
measurable today, from data already stored, without claiming anything.

## The colours here mean something else again

    green   on track — enough checks arriving to reach a verdict
    amber   accumulating, still far from any judgement
    grey    stalled — the count is not moving, which is a fault not a finding

Grey is the useful one. It is the state that says something is wrong with the
plumbing rather than with the market, and nothing else in the system surfaces
it: a stalled ledger and a quiet market look identical everywhere else.

## Calibration is the honest measure of learning

A model that says 60% and is right 60% of the time is calibrated, even if 60%
is useless for trading. A model that says 60% and is right 45% is miscalibrated
and will not improve by waiting. The Brier score separates those, and it is
readable long before any tier is reachable — roughly 30 resolved forecasts
rather than the hundreds a tier needs.

Honest constraint: calibration says the probabilities are truthful, not that
they are useful. A model calibrated at 50% is perfectly honest and worth
nothing. Reading a good Brier score as evidence of edge is the single most
available mistake here, so the report says so every time.

Largest risk: that a progress bar feels like progress toward profit. It is
progress toward being able to answer the question. Those are different, and if
the answer turns out to be "no edge", this view will have moved steadily green
the whole way there.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .stats import wilson_interval

GREEN, AMBER, GREY = "#00e676", "#ffd93d", "#8b8b9a"

# A tier needs this many resolved forecasts before it can be judged at all.
CHECKS_FOR_VERDICT = 100
# Calibration becomes readable well before that.
CHECKS_FOR_CALIBRATION = 30


@dataclass
class ModelProgress:
    name: str
    made: int
    checked: int
    hits: int
    days: int
    brier: float | None
    per_day: float
    colour: str
    verdict: str
    days_to_verdict: int | None = None


@dataclass
class Progress:
    models: list[ModelProgress] = field(default_factory=list)
    total_made: int = 0
    total_checked: int = 0
    first_record: datetime | None = None
    notes: list[str] = field(default_factory=list)


def _brier(rows: list[tuple[float, int]]) -> float | None:
    """Mean squared error between stated probability and outcome.

    0.00 is perfect, 0.25 is what you get by always saying 50%, and above 0.25
    means the stated confidence is worse than a shrug.
    """
    if not rows:
        return None
    return sum((p - hit) ** 2 for p, hit in rows) / len(rows)


def _band(checked: int, per_day: float, brier: float | None,
          waiting: int = 0) -> tuple[str, str, int | None]:
    # Nothing resolved yet, but forecasts are queued: that is day one, not a
    # stall. Reading zero resolutions as a broken ledger is precisely the
    # confusion this module exists to prevent, and it was written into the
    # module itself.
    if per_day <= 0 and waiting > 0:
        return AMBER, (f"{waiting} forecast(s) recorded and none scored yet. "
                       "The first batch is checked 24 hours after it was made, "
                       "so this is the beginning rather than a fault."), None
    if per_day <= 0:
        return GREY, ("Nothing has been recorded in the last week. That is a "
                      "fault in the plumbing, not a quiet market — a stalled "
                      "ledger and a calm week look identical everywhere else "
                      "in this system."), None

    remaining = max(CHECKS_FOR_VERDICT - checked, 0)
    days = int(remaining / per_day) + 1 if remaining else 0

    if checked >= CHECKS_FOR_VERDICT:
        note = ""
        if brier is not None:
            note = (f" Brier {brier:.3f}, where 0.25 is what always saying 50% "
                    "earns." if brier <= 0.25 else
                    f" Brier {brier:.3f} — above 0.25, so the stated confidence "
                    "is worse than a shrug. More data will not fix that.")
        # The score used to print only in the middle band, disappearing exactly
        # when it became most readable.
        return GREEN, ("Enough checks to judge. Whether the answer is good is "
                       "the Board's question, not this one." + note), 0
    if checked >= CHECKS_FOR_CALIBRATION:
        note = ""
        if brier is not None:
            note = (f" Calibration is readable: Brier {brier:.3f}, where 0.25 "
                    "is what always saying 50% earns."
                    if brier <= 0.25 else
                    f" Brier {brier:.3f} — above 0.25, meaning the stated "
                    "confidence is currently worse than a shrug. More data "
                    "will not fix that on its own.")
        return (GREEN if (brier or 1) <= 0.25 else AMBER,
                f"{checked} checked, {remaining} to go at {per_day:.0f} a day — "
                f"about {days} days.{note}", days)
    return AMBER, (f"{checked} checked. Calibration becomes readable at "
                   f"{CHECKS_FOR_CALIBRATION}, a verdict at "
                   f"{CHECKS_FOR_VERDICT} — roughly {days} days at "
                   f"{per_day:.0f} a day."), days


def measure(db_path: str, window_days: float = 7.0) -> Progress:
    """Read the ledger and report whether it is filling.

    `window_days` is clamped to at least one: a fractional window divides a
    handful of records by a fraction of a day and reports thousands per day,
    which would paint a stalled system green.
    """
    window_days = max(float(window_days), 1.0)
    out = Progress()
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    try:
        with sqlite3.connect(db_path) as con:
            out.total_made, out.total_checked = con.execute(
                "SELECT COUNT(*), COUNT(hit) FROM predictions").fetchone()
            earliest = con.execute(
                "SELECT MIN(created_at) FROM predictions").fetchone()[0]
            if earliest:
                out.first_record = datetime.fromisoformat(earliest)

            models = [r[0] for r in con.execute(
                "SELECT DISTINCT model FROM predictions").fetchall()]
            for model in models:
                made, checked, hits = con.execute(
                    "SELECT COUNT(*), COUNT(hit), COALESCE(SUM(hit),0) "
                    "FROM predictions WHERE model=?", (model,)).fetchone()
                recent = con.execute(
                    "SELECT COUNT(hit) FROM predictions WHERE model=? "
                    "AND created_at>=?", (model, since)).fetchone()[0]
                rows = con.execute(
                    "SELECT score, hit FROM predictions WHERE model=? "
                    "AND hit IS NOT NULL AND score IS NOT NULL",
                    (model,)).fetchall()

                waiting = con.execute(
                    "SELECT COUNT(*) FROM predictions WHERE model=? "
                    "AND hit IS NULL", (model,)).fetchone()[0]
                per_day = recent / window_days
                brier = _brier([(float(s), int(h)) for s, h in rows])
                colour, verdict, days = _band(checked, per_day, brier, waiting)
                spread = con.execute(
                    "SELECT COUNT(DISTINCT date(resolve_after)) FROM predictions "
                    "WHERE model=? AND hit IS NOT NULL", (model,)).fetchone()[0]
                out.models.append(ModelProgress(
                    model, made, checked, hits, spread, brier, per_day, colour,
                    verdict, days))
    except sqlite3.Error as exc:
        out.notes.append(f"The ledger could not be read ({exc}). That is worth "
                         "looking at before anything else here is believed.")
        return out

    if not out.models:
        out.notes.append(
            "No forecasts recorded at all. Nothing is accumulating, so nothing "
            "can be learned — check that the daily job is running before "
            "reading any silence as a market observation.")
    return out


def render(progress: Progress) -> str:
    lines = ["How the learning is going", ""]
    if progress.first_record:
        age = (datetime.now(timezone.utc) - progress.first_record).days
        lines.append(f"Recording for {age} day(s). "
                     f"{progress.total_made} forecasts made, "
                     f"{progress.total_checked} scored.")
    else:
        lines.append(f"{progress.total_made} forecasts made, "
                     f"{progress.total_checked} scored.")
    lines.append("")

    for model in progress.models:
        mark = {GREEN: "on track", AMBER: "accumulating", GREY: "STALLED"}[model.colour]
        lines.append(f"{model.name} — {mark}")
        lines.append(f"  {model.verdict}")
        if model.checked >= CHECKS_FOR_CALIBRATION:
            low, _high = wilson_interval(model.hits, model.checked, 0.90)
            lines.append(f"  {model.hits}/{model.checked} right so far, worst "
                         f"case {low:.0%} on a count that assumes every check "
                         "is independent.")
            if model.days:
                lines.append(f"  Those {model.checked} checks came from "
                             f"{model.days} market day(s). On a day the market "
                             "falls most BUY calls fail together, so the real "
                             f"sample is nearer {model.days} than "
                             f"{model.checked} and the interval above is "
                             "tighter than the data supports.")
        lines.append("")

    lines += progress.notes
    lines.append("These colours are about whether the question can be answered, "
                 "not about whether the answer is yes. A model calibrated "
                 "perfectly at 50% would show green here and be worth nothing. "
                 "The Board is where usefulness is judged.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .config import SETTINGS

    ap = argparse.ArgumentParser(description="Is the system learning?")
    ap.add_argument("--db", default=SETTINGS.shadow_db)
    ap.add_argument("--window", type=int, default=7,
                    help="days used to estimate the current rate")
    args = ap.parse_args(argv)

    print(render(measure(args.db, args.window)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
