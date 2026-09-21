"""Priority: spend attention where the opportunity decays fastest.

THE PROBLEM
-----------
Every job ran on a fixed schedule with equal standing. A news reaction and a
slow stock setup were treated as the same kind of thing, and the 3-hour slot
went to crypto15m — measured at no edge across 5,135 checks — on equal footing
with news.

That is not how an experienced trader spends a day. They do not wait for
something to clear a gate and then consider it; they hunt, and they spend
attention on whatever is most time-sensitive first. A market-moving headline
is worth something for hours. An IPO window, for days. A price setup, for a
session. A long-term theme, for weeks. Treating those identically means the
fast-decaying opportunities are processed too late to be worth anything, and
the slow ones get more attention than they need.

THE RULE
--------
Every job carries a HALF-LIFE: how long until an opportunity it finds has lost
half its value. Jobs run in order of urgency — shortest half-life first — and
each run has a time budget. When the budget runs out, the slowest-decaying
jobs are deferred to the next run, because deferring them costs least.

Urgency is then WEIGHTED BY EVIDENCE. A job that has proved it finds nothing
worth acting on should not keep consuming attention at full priority simply
because its window is short. That is the difference between being responsive
and being busy: a professional who has learned a source is noise stops
reading it first, however fast it moves.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# How long, in hours, before an opportunity this job finds loses half its
# value. Shortest runs first.
HALF_LIFE_HOURS: dict[str, float] = {
    # resolve: smallest half-life of all — a forecast that passes its due
    # window can no longer be scored.  Not in the 3-hour queue above because
    # it is called unconditionally at the top of every tick; listed here so
    # the queue knows its priority when selecting jobs in budget.
    "resolve": 1.0,
    "news": 4.0,            # a headline is priced within hours
    "contagion": 24.0,      # follow-on moves play out over a session or two
    "opportunity": 48.0,    # listings and event windows run for days
    "stocks": 24.0,         # a price setup is good for about a session
    "crypto15m": 3.0,       # fast-decaying — but see the evidence weighting
    "profiles": 24.0 * 30,  # how a name behaves changes over months
}
# `thematic` was listed here with no runner behind it, so the queue would
# have scheduled work that could never execute. Add it back only alongside
# its job.

# Bookkeeping that must always run and is never deferred, whatever the budget.
# Resolving closes out open forecasts, which every other measurement depends
# on; skipping it to save time would corrupt the thing the time was saved for.
ALWAYS_RUN = ("resolve",)

# Seconds a single run may spend on discretionary jobs before the slowest
# decaying ones are deferred.
DEFAULT_BUDGET_SECONDS = 20 * 60

# Typical seconds each job takes, so the budget can be planned rather than
# discovered by running out.
TYPICAL_SECONDS: dict[str, float] = {
    "news": 90, "contagion": 240, "opportunity": 120, "stocks": 600,
    "setups": 300, "crypto15m": 180, "daily": 300, "profiles": 600,
}


@dataclass(frozen=True)
class Slot:
    """One job's place in the queue, and why."""

    job: str
    half_life_hours: float
    evidence_weight: float
    urgency: float
    runs: bool
    reason: str


def evidence_weight(verdict: str | None) -> float:
    """How much a job's own record should scale its urgency, 0.1 to 1.0.

    Driven by the same verdicts `diagnose` produces, so a job's priority falls
    automatically once its record shows it finds nothing — rather than someone
    having to remember to demote it.

      WORKING    1.0  proven useful; full priority
      TOO EARLY  1.0  unknown yet; it needs attention to find out
      NO DATA    0.9  nothing recorded, which is worth investigating
      BAD DATA   0.8  a data fault, not a signal fault; still needs running
      NO ROOM    0.4  the horizon defeats it
      NO EDGE    0.1  proven to find nothing — run rarely, not never

    NO EDGE is 0.1 rather than zero on purpose. Conditions change, and a model
    that is never run can never be seen to recover. Running it rarely keeps a
    thin record growing at almost no cost.
    """
    return {
        "WORKING": 1.0,
        "TOO EARLY": 1.0,
        "NO DATA": 0.9,
        "BAD DATA": 0.8,
        "NO ROOM": 0.4,
        "NO EDGE": 0.1,
    }.get((verdict or "TOO EARLY").upper(), 1.0)


def plan(jobs: Sequence[str], verdicts: dict[str, str] | None = None,
         budget_seconds: float = DEFAULT_BUDGET_SECONDS) -> list[Slot]:
    """Order jobs by weighted urgency and decide which fit this run.

    Urgency is 1/half-life times the evidence weight: fast-decaying and
    useful comes first, slow-decaying or proven-useless comes last. Jobs are
    admitted in that order until the budget is spent.
    """
    verdicts = verdicts or {}
    slots = []
    for job in jobs:
        if job in ALWAYS_RUN:
            continue
        half = HALF_LIFE_HOURS.get(job, 24.0)
        weight = evidence_weight(verdicts.get(job))
        slots.append((job, half, weight, weight / half))

    slots.sort(key=lambda s: -s[3])

    out: list[Slot] = [Slot(job, 0.0, 1.0, float("inf"), True,
                            "Always runs: every measurement depends on "
                            "forecasts being closed out.")
                       for job in ALWAYS_RUN if job in jobs]
    spent = 0.0
    # The highest evidence weight of any job skipped so far. A later job may
    # only use leftover budget if it deserves attention at least as much.
    #
    # Without this, admission was plain greedy bin-packing, and it produced
    # exactly the wrong result on the first real run: contagion (unexplored,
    # weight 0.9) did not fit, and crypto15m (proven to find nothing, weight
    # 0.1) slipped into the gap because it happened to be cheaper. A queue
    # ordered by urgency was quietly letting the least deserving job jump it
    # on cost alone.
    best_skipped = 0.0
    for job, half, weight, urgency in slots:
        cost = TYPICAL_SECONDS.get(job, 180)
        fits = spent + cost <= budget_seconds and weight >= best_skipped
        if fits:
            spent += cost
        else:
            best_skipped = max(best_skipped, weight)
        if weight <= 0.15:
            reason = ("Record shows it finds nothing worth acting on, so it "
                      "runs at a tenth of its natural priority — rarely, so a "
                      "recovery would still be seen.")
        elif half <= 6:
            reason = (f"Opportunities it finds lose half their value in about "
                      f"{half:.0f} hours, so it goes first.")
        elif half >= 24 * 7:
            reason = ("Slow-moving: what it finds is still worth nearly as "
                      "much next week, so it yields to anything faster.")
        else:
            reason = (f"Opportunities last about {half / 24:.0f} day(s); "
                      "middle of the queue.")
        if not fits:
            reason += (" Deferred this run — the budget went to faster-"
                       "decaying work, which is the cheapest thing to delay.")
        out.append(Slot(job, half, weight, round(urgency, 4), fits, reason))
    return out


def describe(slots: Sequence[Slot]) -> str:
    """The queue as a person would want to read it."""
    lines = ["Attention, in order of urgency", ""]
    for i, s in enumerate(slots, 1):
        mark = "RUN     " if s.runs else "DEFERRED"
        lines.append(f"  {i:>2}. [{mark}] {s.job}")
        lines.append(f"      {s.reason}")
    deferred = [s for s in slots if not s.runs]
    lines.append("")
    if deferred:
        lines.append(f"  {len(deferred)} job(s) deferred. Nothing is dropped — "
                     "they run next time, when the faster work is done.")
    lines.append("  Fast-decaying opportunities are handled first because a "
                 "headline acted on tomorrow is worth nothing, while a "
                 "long-term theme read tomorrow is worth nearly as much.")
    return "\n".join(lines)
