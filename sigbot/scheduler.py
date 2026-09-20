"""The 24/7 heartbeat — runs tasks in parallel, on the right clock, out loud.

Replaces the scheduler in the specification, which had three faults that would
each have been expensive:

  `datetime.now()` for US market hours   From Delhi this inverts every US
                                         decision: it polls NYSE at 23:00-05:30
                                         New York and skips the real session.
                                         Uses `market_hours` here instead.

  `await task.coro()` inside the loop    Serial. A twenty-minute screen blocks
                                         crypto ticks for twenty minutes, which
                                         in a system built for continuous
                                         operation is the opposite of the point.
                                         Tasks run concurrently here.

  `_log_failure` as `pass`               Under a comment reading "Fail-loud: do
                                         not swallow". Failures go to the skip
                                         ledger here, with the traceback.

## Gap detection lives here, not in a separate module

A gap is not a property of the data, it is the difference between what should
have run and what did. The scheduler is the only thing that knows both. When
`market_hours` says a venue was open and a task did not succeed inside its
window, that is recorded as a gap — distinct from a task that failed, and
distinct again from a market that was simply closed. Collapsing those three is
how a sleeping laptop becomes "no signal".

Honest constraint: nothing runs while the Mac is asleep. On wake, overdue tasks
run immediately and the sleep is recorded as a gap, but real-time data that
arrived during the sleep is gone and no amount of catching up recovers it.

Largest risk: that a long uptime feels like continuous coverage. `report()`
prints gaps and consecutive failures for exactly this reason — read it before
trusting a stretch of quiet.

Test gap: macOS sleep/wake cannot be simulated here, so wake handling is tested
by moving the injected clock forward, which is not the same thing.
"""
from __future__ import annotations

import asyncio
import inspect
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta, timezone

from .market_hours import Venue, is_open, should_poll
from .skips import record_skip

MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class Task:
    """One thing to run, and the conditions under which it should run."""
    name: str
    run: Callable                      # sync or async; sync goes to a thread
    interval: timedelta
    venue: Venue | None = None         # gate on this venue's session
    run_on_start: bool = False
    timeout: float = 1800.0            # 30 min; a screen is the long pole

    last_attempt: datetime | None = None
    # When the scheduler first saw this task, so a job without
    # run_on_start still has a clock to measure its interval from.
    first_seen: datetime | None = None
    last_success: datetime | None = None
    consecutive_failures: int = 0
    runs: int = 0
    gaps: int = 0
    _running: bool = field(default=False, repr=False)

    def due(self, now: datetime) -> bool:
        if self._running:
            return False               # never start a second copy
        if self.last_attempt is None:
            # A task that has never run must become due, or it waits forever
            # for a first run this gate will not grant: last_attempt is only
            # set by running, and running requires being due. Six of eight
            # tasks sat at "0 runs, last attempt never" for days because of
            # this — alive, scheduled, and silently never called.
            #
            # `run_on_start` now means "immediately" rather than "ever": with
            # it the task fires on the first tick, without it after one
            # interval. It was never meant to decide whether a job runs at all.
            if self.run_on_start:
                return True
            self.first_seen = self.first_seen or now
            return now - self.first_seen >= self.interval
        # A job on a daily interval that is also gated to a market window has
        # to satisfy both at once. Measuring 24 hours from the last attempt
        # pins the next one to whatever time that was — and a single run
        # outside the window, manual or after a restart, pins it outside the
        # window permanently. It then waits a day, misses again, and never
        # catches up.
        #
        # So a daily job asks "have I run today" rather than "has a day
        # passed". Sub-daily jobs keep the elapsed-time rule, where drift of a
        # few seconds does not matter.
        if self.interval >= timedelta(days=1):
            return self._calendar_date(now) != self._calendar_date(self.last_attempt)
        return now - self.last_attempt >= self.interval

    def _calendar_date(self, when: datetime):
        """The date in the venue's own timezone, so "today" means the trading
        day rather than a UTC one that splits an Indian session."""
        if self.venue is None:
            return when.date()
        from zoneinfo import ZoneInfo

        from .market_hours import SESSIONS

        return when.astimezone(ZoneInfo(SESSIONS[self.venue].tz)).date()

    def gated(self, now: datetime) -> tuple[bool, str]:
        if self.venue is None or self.venue is Venue.CRYPTO:
            return True, "always on"
        if is_open(self.venue, now):
            return True, "market open"
        return False, f"{self.venue.value} closed"

    @property
    def healthy(self) -> bool:
        return self.consecutive_failures < MAX_CONSECUTIVE_FAILURES


class Scheduler:
    """Runs registered tasks concurrently, forever or for a fixed number of ticks.

    `clock` exists so tests can move time without sleeping. Production passes
    nothing and gets the real UTC clock.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None,
                 on_alert: Callable[[str], None] | None = None):
        self.tasks: list[Task] = []
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.on_alert = on_alert
        self.started: datetime | None = None
        self.ticks = 0
        self._stop = False

    def register(self, task: Task) -> Task:
        if any(t.name == task.name for t in self.tasks):
            raise ValueError(f"duplicate task name: {task.name}")
        self.tasks.append(task)
        return task

    def stop(self) -> None:
        self._stop = True

    # ---------------------------------------------------------- one task
    async def _execute(self, task: Task) -> bool:
        now = self.clock()
        task._running = True
        task.last_attempt = now
        try:
            if inspect.iscoroutinefunction(task.run):
                await asyncio.wait_for(task.run(), timeout=task.timeout)
            else:
                # A synchronous job goes to a thread so it cannot block the loop.
                # This is the difference between a scheduler and a queue.
                await asyncio.wait_for(asyncio.to_thread(task.run),
                                       timeout=task.timeout)
        except asyncio.TimeoutError as exc:
            task.consecutive_failures += 1
            record_skip("scheduler", task.name, exc)
            self._save()
            print(f"[scheduler] {task.name} timed out after {task.timeout:.0f}s")
            self._maybe_alert(task)
            return False
        except Exception as exc:  # noqa: BLE001 - one bad task must not stop the rest
            task.consecutive_failures += 1
            record_skip("scheduler", task.name, exc)
            self._save()
            print(f"[scheduler] {task.name} failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            self._maybe_alert(task)
            return False
        else:
            task.consecutive_failures = 0
            task.last_success = self.clock()
            task.runs += 1
            # After the counter, not before — an earlier ordering saved runs=0
            # on every success, so the status file said the daemon had never
            # completed anything while it was working perfectly.
            self._save()
            return True
        finally:
            task._running = False

    def _maybe_alert(self, task: Task) -> None:
        if task.consecutive_failures == MAX_CONSECUTIVE_FAILURES and self.on_alert:
            self.on_alert(
                f"{task.name} has failed {task.consecutive_failures} times in a "
                "row. It is no longer running successfully, and its silence is "
                "not a market observation.")

    # ------------------------------------------------------------- gaps
    def _check_gaps(self, now: datetime) -> None:
        """A gap is what should have run and did not.

        Distinct from a failure, and distinct from a closed market. Collapsing
        the three is how a sleeping laptop becomes "no signal".
        """
        for task in self.tasks:
            if task.last_success is None:
                continue
            overdue = now - task.last_success
            if overdue <= task.interval * 3:
                continue
            open_now, _ = task.gated(now)
            if not open_now:
                continue               # closed markets are not gaps
            task.gaps += 1
            record_skip("scheduler_gap", task.name,
                        RuntimeError(f"no successful run for {overdue}, "
                                     f"interval is {task.interval}"))

    # -------------------------------------------------------------- loop
    async def tick(self) -> list[str]:
        """One pass. Returns the names of tasks that were started."""
        now = self.clock()
        self.ticks += 1
        self._check_gaps(now)

        ready = []
        for task in self.tasks:
            if not task.due(now):
                continue
            allowed, _reason = task.gated(now)
            if not allowed:
                task.last_attempt = now     # do not re-check every second
                continue
            ready.append(task)

        if ready:
            # Concurrently, so the slowest task sets the latency of nothing but
            # itself. gather with return_exceptions because _execute already
            # records its own failures.
            await asyncio.gather(*(self._execute(t) for t in ready),
                                 return_exceptions=True)
        return [t.name for t in ready]

    async def run(self, poll_seconds: float = 1.0, max_ticks: int | None = None):
        self.started = self.clock()
        self._stop = False
        print(f"[scheduler] started with {len(self.tasks)} task(s)")
        while not self._stop:
            await self.tick()
            if max_ticks is not None and self.ticks >= max_ticks:
                break
            await asyncio.sleep(poll_seconds)
        print(f"[scheduler] stopped after {self.ticks} tick(s)")

    # ------------------------------------------------------------ status
    # ------------------------------------------------------ persisted state
    # Task counters lived only in memory, so `--status` — which starts a fresh
    # process — always printed zeros regardless of what the daemon was doing.
    # A status command that cannot see the running system is worse than none:
    # it answers the question wrongly instead of admitting it cannot.
    STATE_FILE = "scheduler_state.json"

    def _save(self) -> None:
        import json

        try:
            Path(self.STATE_FILE).write_text(json.dumps({
                t.name: {
                    "runs": t.runs,
                    "gaps": t.gaps,
                    "consecutive_failures": t.consecutive_failures,
                    "last_success": (t.last_success.isoformat()
                                     if t.last_success else None),
                    "last_attempt": (t.last_attempt.isoformat()
                                     if t.last_attempt else None),
                } for t in self.tasks
            }, indent=1), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001  # handled: recorded; losing the status file must never stop a run
            record_skip("scheduler_state", self.STATE_FILE, exc)

    def load_state(self) -> bool:
        """Fill task counters from the file the daemon writes.

        Returns whether anything was read, so a caller can say "no daemon has
        run" rather than showing zeros that look like a dead system.
        """
        import json
        from datetime import datetime as _dt

        path = Path(self.STATE_FILE)
        if not path.exists():
            return False
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001  # handled: recorded, and reported as "no state" to the caller
            record_skip("scheduler_state", self.STATE_FILE, exc)
            return False

        for task in self.tasks:
            row = saved.get(task.name)
            if not row:
                continue
            task.runs = row.get("runs", 0)
            task.gaps = row.get("gaps", 0)
            task.consecutive_failures = row.get("consecutive_failures", 0)
            for field_name in ("last_success", "last_attempt"):
                raw = row.get(field_name)
                if raw:
                    setattr(task, field_name, _dt.fromisoformat(raw))
        return True

    def report(self) -> str:
        now = self.clock()
        lines = []
        if self.started:
            up = now - self.started
            lines.append(f"Up {up.days}d {up.seconds // 3600}h, {self.ticks} ticks.")
        for task in sorted(self.tasks, key=lambda t: t.name):
            when = ("never" if task.last_success is None
                    else f"{(now - task.last_success).total_seconds() / 60:.0f}m ago")
            state = "ok" if task.healthy else "FAILING"
            allowed, why = task.gated(now)
            line = (f"  {task.name:<22} {state:<8} {task.runs:>4} runs, "
                    f"last success {when}")
            if not allowed:
                line += f" [{why}]"
            if task.gaps:
                line += f"  {task.gaps} gap(s)"
            lines.append(line)
        broken = [t.name for t in self.tasks if not t.healthy]
        if broken:
            lines.append(f"\nNot running: {', '.join(broken)}. Their silence is "
                         "not a market observation.")
        return "\n".join(lines)


def poll_gate(symbol: str, when: datetime | None = None) -> tuple[bool, str]:
    """Whether a symbol should be fetched now. Re-exported for callers."""
    return should_poll(symbol, when)
