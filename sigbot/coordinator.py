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

# (name, runner attribute, interval, venue gate)
JOBS: list[tuple[str, str, timedelta, Venue | None]] = [
    # Four-hourly. The feed does not turn over faster than that, and
    # the scan only speaks when something is new.
    ("opportunities", "run_opportunities", timedelta(hours=4), None),
    ("news", "run_news", timedelta(hours=2), None),
    # Every fifteen minutes, always: crypto does not close, and the whole
    # point of this model is that its evidence arrives ninety-six times faster
    # than the daily one's.
    # Hourly. Every fifteen minutes produced ~9,600 forecasts a day whose
    # errors were almost entirely shared — volume, not information — and made
    # every page unreadable. The horizon is one hour, so scoring once per
    # horizon loses nothing that mattered.
    ("crypto15m", "run_crypto15m", timedelta(hours=3), None),
    # After resolve, so it replays predictions scored in the same cycle.
    ("paper", "run_paper", timedelta(hours=3), None),
    ("resolve", "run_resolve", timedelta(minutes=30), None),
    ("daily", "run_daily", timedelta(hours=24), None),
    ("contagion", "run_contagion", timedelta(hours=24), None),
    # Hourly, but it only speaks once, after the last close.
    ("day_summary", "run_day_summary", timedelta(hours=1), None),
    ("publish", "run_publish", timedelta(minutes=30), None),
    ("cycle", "run_cycle", timedelta(days=7), None),
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


def build(scheduler: Scheduler | None = None, jobs=None) -> Scheduler:
    """Register the runner's jobs. Missing jobs are reported, not fatal."""
    from . import runner

    sched = scheduler or Scheduler(on_alert=_alert)
    for name, attr, interval, venue in (jobs or JOBS):
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
