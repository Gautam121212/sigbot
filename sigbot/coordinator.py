"""The coordinator — schedules what already exists.

    python -m sigbot.coordinator            # run forever
    python -m sigbot.coordinator --status   # show the task table and exit
    python -m sigbot.coordinator --once     # one pass, for checking wiring

Deliberately thin. Every job here is an existing `runner.py` function; nothing
reimplements pipeline logic. The only thing this adds is *when* things happen,
which is the whole gap between a daily batch and continuous operation.

## What runs, and how often

  news        every 2 hours          the one thing that genuinely goes stale
  resolve     every 30 minutes       scores predictions as their horizons pass,
                                     rather than once a day at a fixed hour
  daily       once a day, 20:30 IST  reads daily bars; running it more often
                                     returns the identical answer until a new
                                     bar closes
  contagion   once a day             same reason
  publish     every 3 hours          rebuilds the page and sends it,
                                     replacing the previous one so the
                                     chat holds exactly one, always current
  cycle       weekly, Monday         re-screen, re-learn weights, rotate

Honest constraint: nothing runs while the Mac is asleep. Overdue tasks run on
wake and the sleep is recorded as a gap, but real-time data from that window is
gone. `caffeinate -s` while running, or accept the gaps and read them.

Largest risk: that continuous uptime is mistaken for continuous coverage. Most
of these jobs read daily bars, so running the coordinator does not make the
models faster — it makes them punctual, and it keeps the news scan current.
Anything claiming a daily-bar model benefits from a five-minute loop is
describing an expectation, not a mechanism.

Test gap: the real jobs are not exercised here, only their scheduling. Each
job has its own tests.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

from .market_hours import Venue, status
from .scheduler import Scheduler, Task

# ── OperatingLoop integration (Commit A: alongside, not replacing, old jobs) ──
_LOOP_INSTANCE = None  # OperatingLoop | None, imported lazily
_LOOP_ENABLED = True      # Commit B: loop is now the single prediction path

# (name, runner attribute, interval, venue gate)
# COMMIT B: the five old prediction jobs (stocks, news, crypto, ventures, ideas)
# are replaced by the single OperatingLoop job. The old runners remain in
# runner.py and can still be called directly for diagnostics, but they are no
# longer in the schedule — they cannot independently mint predictions.
#
# If you need to roll back: restore the old JOBS list and set _LOOP_ENABLED=False.
JOBS: list[tuple[str, str, timedelta, Venue | None]] = [
    # After resolve, so it replays predictions scored in the same cycle.
    # ── Commit B: single operating loop replaces the five old prediction jobs ──
    # market-aware, event-driven, fail-closed, all through OperatingLoop.tick()
    ("operating_loop", "run_operating_loop_tick", timedelta(minutes=15), None),
    ("paper", "run_paper", timedelta(hours=3), None),
    ("resolve", "run_resolve", timedelta(minutes=30), None),
    # Hourly, but it only speaks once, after the last close.
    ("day_summary", "run_day_summary", timedelta(hours=1), None),
    ("publish", "run_publish", timedelta(minutes=30), None),
    ("cycle", "run_cycle", timedelta(days=7), None),
    # Retired models (crypto15m intra-day, daily duplicate, contagion) removed
    # from the schedule — they no longer run. crypto15m was intra-day (no forward
    # edge); daily is now the once-a-day "stocks" job above; contagion retired.
]


def load_env(root: str | None = None) -> int:
    """Read .env into the environment. launchd inherits no shell.

    Without this the agent starts, runs, and silently cannot deliver anything,
    which looks identical to a market with nothing to say.
    """
    import os
    from pathlib import Path

    env = Path(root or Path(__file__).resolve().parent.parent) / ".env"
    if not env.exists():
        return 0
    loaded = 0
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            loaded += 1
    return loaded


def _alert(message: str) -> None:
    """Tell the operator a task has stopped working. Never raises."""
    print(f"[coordinator] ALERT: {message}")
    try:
        from .setup_delivery import send

        send(f"Sigbot task problem\n\n{message}")
    except Exception as exc:  # noqa: BLE001
        # Delivery is best-effort; the message is already on stdout and in the
        # log file, so a failure here must not take the scheduler down with it.
        print(f"[coordinator] could not send the alert: {type(exc).__name__}: {exc}")


def _run_operating_loop_tick() -> None:
    """One tick of the market-aware OperatingLoop. Called by the coordinator as
    a scheduled job when _LOOP_ENABLED is True. Fail-closed: an exception here
    is caught by the scheduler's error handler, not silently swallowed."""
    if not _LOOP_ENABLED:
        return
    global _LOOP_INSTANCE
    from .live_handlers import LiveHandlers, RealSetupSources
    from .shadow import ShadowLedger
    from .providers.market import YahooProvider
    from .config import SETTINGS
    src = RealSetupSources(settings=SETTINGS)
    # Ventures' PREDICT event is backlog-gated in the scheduler: pre-scan once so
    # plan_tick emits PREDICT_NEXT_SESSION only when a concrete thesis is ready,
    # and the handler records from that same scan (no double work). Stocks stays
    # lazy — its predict event is unconditional when closed/preopen.
    ventures_setups = src.ventures()
    # News is event-queued: the scheduler emits PREDICT_CURRENT_SESSION only when
    # news_queue > 0, so pre-scan once and pass the count. Same capture pattern
    # as ventures; src.news() is fail-closed (returns [] on a scan error).
    news_setups = src.news()
    if _LOOP_INSTANCE is None:
        from .operating_loop_v2 import OperatingLoop
        ledger = ShadowLedger(SETTINGS.shadow_db)
        market = YahooProvider()
        handlers = LiveHandlers(ledger=ledger, market=market,
                                stocks_setups=src.stocks)
        _LOOP_INSTANCE = OperatingLoop(handlers=handlers)
    # refresh setup sources for this tick
    _LOOP_INSTANCE.handlers.stocks_setups = src.stocks
    _LOOP_INSTANCE.handlers.ventures_setups = lambda: ventures_setups
    _LOOP_INSTANCE.handlers.news_setups = lambda: news_setups
    _LOOP_INSTANCE.tick(ventures_backlog=len(ventures_setups),
                        news_queue=len(news_setups))


def build(scheduler: Scheduler | None = None, jobs=None) -> Scheduler:
    """Register the runner's jobs. Missing jobs are reported, not fatal."""
    from . import runner

    sched = scheduler or Scheduler(on_alert=_alert)
    for name, attr, interval, venue in (jobs or JOBS):
        if attr == "run_operating_loop_tick":
            fn = _run_operating_loop_tick       # defined here in coordinator, not runner
        else:
            fn = getattr(runner, attr, None)
        if fn is None:
            print(f"[coordinator] {attr} not found in runner — skipping {name}")
            continue
        sched.register(Task(name=name, run=fn, interval=interval, venue=venue,
                            # Everything runs once on startup. A daily job on a
                            # 24-hour timer that is also gated to a 6-hour
                            # market window has to have both align: the timer
                            # expired eleven minutes before the bell, so it
                            # waited another full day, and another. `daily` is
                            # the only job that makes predictions, so the ledger
                            # stayed empty and the day summary reported zero
                            # made — which reads as "nothing passed the gates"
                            # when in truth nothing was ever proposed.
                            #
                            # A job that is out of session on startup still
                            # waits for its venue; it simply no longer waits a
                            # full interval on top of that.
                            run_on_start=True))
    return sched


async def _run(poll_seconds: float, max_ticks: int | None) -> int:
    loaded = load_env()
    if loaded:
        print(f"[coordinator] loaded {loaded} setting(s) from .env")
    sched = build()
    if not sched.tasks:
        print("[coordinator] no tasks registered — nothing to run.")
        return 1
    print(status())
    print()
    try:
        await sched.run(poll_seconds=poll_seconds, max_ticks=max_ticks)
    except KeyboardInterrupt:
        sched.stop()
        print("\n[coordinator] stopped by hand")
    print("\n" + sched.report())
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the sigbot jobs continuously.")
    ap.add_argument("--status", action="store_true", help="print the table and exit")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--poll", type=float, default=30.0,
                    help="seconds between checks (default 30)")
    args = ap.parse_args(argv)

    if args.status:
        sched = build()
        print(status())
        print()
        # Read what the running daemon wrote. Without this the command builds
        # a fresh scheduler and prints its empty counters, which looks exactly
        # like a system that has never run.
        if not sched.load_state():
            print("No scheduler state on disk yet. Either nothing has run, or "
                  "the daemon is not writing here — check that autostart.sh "
                  "points at this folder.\n")
        print(sched.report())
        return 0

    return asyncio.run(_run(args.poll, max_ticks=1 if args.once else None))


if __name__ == "__main__":
    sys.exit(main())
