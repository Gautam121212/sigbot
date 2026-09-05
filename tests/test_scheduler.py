"""Tests for the scheduler and coordinator.

Three of these correspond directly to faults in the proposed version: serial
execution, local-time market hours, and a `_log_failure` that was `pass`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from sigbot import coordinator
from sigbot.market_hours import Venue
from sigbot.scheduler import MAX_CONSECUTIVE_FAILURES, Scheduler, Task
from sigbot.skips import reset, skipped_count

IST = ZoneInfo("Asia/Kolkata")


class Clock:
    """Injected time, so a test can wait an hour without waiting an hour."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


@pytest.fixture
def clock():
    return Clock(datetime(2026, 8, 31, 12, tzinfo=IST))      # Monday, NSE open


# ------------------------------------------------------------ scheduling

def test_a_task_runs_on_start_then_waits(clock):
    calls = []
    s = Scheduler(clock=clock)
    s.register(Task("t", lambda: calls.append(1), timedelta(hours=1),
                    run_on_start=True))

    asyncio.run(s.tick())
    assert len(calls) == 1

    asyncio.run(s.tick())
    assert len(calls) == 1, "ran again before its interval elapsed"

    clock.advance(hours=1)
    asyncio.run(s.tick())
    assert len(calls) == 2


def test_a_task_without_run_on_start_waits_one_interval(clock):
    calls = []
    s = Scheduler(clock=clock)
    s.register(Task("t", lambda: calls.append(1), timedelta(minutes=30)))
    asyncio.run(s.tick())
    assert calls == []


def test_duplicate_names_are_refused(clock):
    s = Scheduler(clock=clock)
    s.register(Task("t", lambda: None, timedelta(hours=1)))
    with pytest.raises(ValueError, match="duplicate"):
        s.register(Task("t", lambda: None, timedelta(hours=1)))


# ------------------------------------------ the serial-execution fault

def test_a_slow_task_does_not_block_a_fast_one(clock):
    """The proposed version awaited each task in turn, so a twenty-minute
    screen blocked crypto ticks for twenty minutes."""
    order = []

    async def slow():
        await asyncio.sleep(0.15)
        order.append("slow")

    async def fast():
        await asyncio.sleep(0.01)
        order.append("fast")

    s = Scheduler(clock=clock)
    s.register(Task("slow", slow, timedelta(hours=1), run_on_start=True))
    s.register(Task("fast", fast, timedelta(hours=1), run_on_start=True))

    asyncio.run(s.tick())
    assert order == ["fast", "slow"], "tasks ran serially"


def test_a_blocking_sync_task_goes_to_a_thread(clock):
    """A synchronous job must not hold the event loop."""
    import time

    order = []

    def blocking():
        time.sleep(0.15)
        order.append("blocking")

    async def quick():
        await asyncio.sleep(0.01)
        order.append("quick")

    s = Scheduler(clock=clock)
    s.register(Task("blocking", blocking, timedelta(hours=1), run_on_start=True))
    s.register(Task("quick", quick, timedelta(hours=1), run_on_start=True))
    asyncio.run(s.tick())
    assert order == ["quick", "blocking"]


def test_a_task_is_never_started_twice(clock):
    running = []

    async def slow():
        running.append(1)
        await asyncio.sleep(0.05)

    s = Scheduler(clock=clock)
    task = s.register(Task("t", slow, timedelta(seconds=0), run_on_start=True))

    async def drive():
        first = asyncio.create_task(s.tick())
        await asyncio.sleep(0.01)
        await s.tick()            # while the first is still running
        await first

    asyncio.run(drive())
    assert len(running) == 1, "a second copy started while the first ran"
    assert not task._running


# ---------------------------------------------- the swallowed-failure fault

def test_a_failure_is_recorded_not_swallowed(clock):
    """The proposed `_log_failure` was `pass`, under a comment saying
    'Fail-loud: do not swallow'."""
    def boom():
        raise ValueError("no data")

    s = Scheduler(clock=clock)
    task = s.register(Task("t", boom, timedelta(hours=1), run_on_start=True))
    asyncio.run(s.tick())

    assert task.consecutive_failures == 1
    assert skipped_count("scheduler") == 1


def test_one_bad_task_does_not_stop_the_others(clock):
    good = []
    s = Scheduler(clock=clock)
    s.register(Task("bad", lambda: 1 / 0, timedelta(hours=1), run_on_start=True))
    s.register(Task("good", lambda: good.append(1), timedelta(hours=1),
                    run_on_start=True))
    asyncio.run(s.tick())
    assert good == [1]


def test_success_clears_the_failure_count(clock):
    state = {"fail": True}

    def flaky():
        if state["fail"]:
            raise RuntimeError("nope")

    s = Scheduler(clock=clock)
    task = s.register(Task("t", flaky, timedelta(minutes=1), run_on_start=True))
    asyncio.run(s.tick())
    assert task.consecutive_failures == 1

    state["fail"] = False
    clock.advance(minutes=1)
    asyncio.run(s.tick())
    assert task.consecutive_failures == 0 and task.runs == 1


def test_the_operator_is_alerted_after_repeated_failures(clock):
    alerts = []
    s = Scheduler(clock=clock, on_alert=alerts.append)
    s.register(Task("t", lambda: 1 / 0, timedelta(minutes=1), run_on_start=True))
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        asyncio.run(s.tick())
        clock.advance(minutes=1)
    assert len(alerts) == 1
    assert "not a market observation" in alerts[0]


def test_a_timeout_is_recorded(clock):
    async def hangs():
        await asyncio.sleep(5)

    s = Scheduler(clock=clock)
    task = s.register(Task("t", hangs, timedelta(hours=1), run_on_start=True,
                           timeout=0.05))
    asyncio.run(s.tick())
    assert task.consecutive_failures == 1 and skipped_count("scheduler") == 1


# ------------------------------------------------- market-hours gating

def test_an_equity_task_waits_for_its_own_exchange(clock):
    """From Delhi, `datetime.now()` would have said NYSE was open at noon IST."""
    calls = []
    s = Scheduler(clock=clock)
    s.register(Task("us", lambda: calls.append(1), timedelta(minutes=5),
                    venue=Venue.NYSE, run_on_start=True))
    asyncio.run(s.tick())
    assert calls == [], "ran while New York was shut"

    clock.now = datetime(2026, 8, 31, 21, tzinfo=IST)     # 11:30 in New York
    clock.advance(minutes=5)
    asyncio.run(s.tick())
    assert calls == [1]


def test_an_indian_task_runs_during_the_indian_session(clock):
    calls = []
    s = Scheduler(clock=clock)
    s.register(Task("in", lambda: calls.append(1), timedelta(minutes=5),
                    venue=Venue.NSE, run_on_start=True))
    asyncio.run(s.tick())
    assert calls == [1]


def test_crypto_is_never_gated(clock):
    calls = []
    s = Scheduler(clock=clock)
    s.register(Task("c", lambda: calls.append(1), timedelta(minutes=5),
                    venue=Venue.CRYPTO, run_on_start=True))
    clock.now = datetime(2026, 8, 30, 3, tzinfo=IST)      # Sunday, 3am
    asyncio.run(s.tick())
    assert calls == [1]


# ------------------------------------------------------------- gaps

def test_a_missed_window_is_recorded_as_a_gap(clock):
    calls = []
    s = Scheduler(clock=clock)
    s.register(Task("t", lambda: calls.append(1), timedelta(minutes=30),
                    run_on_start=True))
    asyncio.run(s.tick())

    clock.advance(hours=6)              # the laptop slept
    asyncio.run(s.tick())
    task = s.tasks[0]
    assert task.gaps >= 1
    assert skipped_count("scheduler_gap") >= 1


def test_a_closed_market_is_not_a_gap(clock):
    """A shut exchange, a failed fetch and a sleeping laptop are three things."""
    s = Scheduler(clock=clock)
    task = s.register(Task("us", lambda: None, timedelta(minutes=30),
                           venue=Venue.NYSE, run_on_start=True))
    task.last_success = clock.now - timedelta(hours=6)
    asyncio.run(s.tick())
    assert task.gaps == 0
    assert skipped_count("scheduler_gap") == 0


def test_a_task_that_never_ran_is_not_a_gap(clock):
    s = Scheduler(clock=clock)
    task = s.register(Task("t", lambda: None, timedelta(minutes=1)))
    clock.advance(days=1)
    asyncio.run(s.tick())
    assert task.gaps == 0


# ------------------------------------------------------------ reporting

def test_the_report_names_what_is_broken(clock):
    s = Scheduler(clock=clock)
    s.register(Task("bad", lambda: 1 / 0, timedelta(minutes=1), run_on_start=True))
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        asyncio.run(s.tick())
        clock.advance(minutes=1)
    text = s.report()
    assert "FAILING" in text and "bad" in text
    assert "not a market observation" in text


def test_run_stops_at_max_ticks(clock):
    s = Scheduler(clock=clock)
    s.register(Task("t", lambda: None, timedelta(hours=1), run_on_start=True))
    asyncio.run(s.run(poll_seconds=0, max_ticks=3))
    assert s.ticks == 3


# ---------------------------------------------------------- coordinator

def test_the_coordinator_schedules_real_runner_jobs():
    from sigbot import runner

    sched = coordinator.build(Scheduler())
    assert sched.tasks, "no jobs registered"
    for task in sched.tasks:
        assert any(getattr(runner, attr, None) is task.run
                   for _, attr, _, _ in coordinator.JOBS), \
            f"{task.name} is not a runner function"


def test_the_coordinator_does_not_reimplement_the_pipeline():
    """It schedules; it must not contain pipeline logic."""
    import inspect as _inspect

    src = _inspect.getsource(coordinator)
    for word in ("wilson", "screen(", "classify_tier", "DataFrame"):
        assert word not in src, f"coordinator contains pipeline logic: {word}"


def test_a_missing_job_is_reported_not_fatal(capsys):
    sched = coordinator.build(Scheduler(),
                              jobs=[("ghost", "run_nonexistent",
                                     timedelta(hours=1), None)])
    assert sched.tasks == []
    assert "not found in runner" in capsys.readouterr().out


def test_daily_is_not_scheduled_more_often_than_daily():
    """Daily bars do not change intraday. A five-minute loop over them returns
    the identical answer and burns the rate limit."""
    by_name = {n: iv for n, _, iv, _ in coordinator.JOBS}
    assert by_name["daily"] >= timedelta(hours=24)
    assert by_name["contagion"] >= timedelta(hours=24)
    assert by_name["news"] <= timedelta(hours=4), "news is the thing that goes stale"


def test_status_mode_runs(capsys):
    assert coordinator.main(["--status"]) == 0
    out = capsys.readouterr().out
    assert "NSE" in out and "NYSE" in out


# ------------------------------------------------------------ autostart

def test_env_is_loaded_because_launchd_has_no_shell(tmp_path, monkeypatch):
    """Without this the agent runs, cannot deliver, and the silence looks
    identical to a market with nothing to say."""
    import os

    (tmp_path / ".env").write_text('TELEGRAM_TOKEN="1:AAH"\nTELEGRAM_CHAT_ID="9"\n')
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert coordinator.load_env(str(tmp_path)) == 2
    assert os.environ["TELEGRAM_TOKEN"] == "1:AAH"


def test_missing_env_is_not_an_error(tmp_path):
    assert coordinator.load_env(str(tmp_path / "nothing")) == 0


def test_an_alert_failure_does_not_take_the_scheduler_down(monkeypatch, capsys):
    """Delivery is best-effort. A dead Telegram must not stop the jobs."""
    import sigbot.setup_delivery as sd

    monkeypatch.setattr(sd, "send", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("telegram down")))
    coordinator._alert("test message")
    out = capsys.readouterr().out
    assert "could not send the alert" in out


def test_autostart_script_is_valid_and_executable():
    import os
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "autostart.sh"
    assert script.exists() and os.access(script, os.X_OK)
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_autostart_keeps_the_agent_alive_and_awake():
    """RunAtLoad starts it at login; KeepAlive restarts it if it dies;
    caffeinate stops the Mac sleeping mid-run."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "autostart.sh").read_text()
    assert "RunAtLoad" in src and "KeepAlive" in src
    assert "caffeinate" in src
    assert "ThrottleInterval" in src
    assert "sigbot.coordinator" in src
    assert ".env" in src, "launchd needs the credentials written down"
    assert "Downloads" in src, "must still warn about protected folders"


# ------------------------------------------------- lid-closed operation

def test_lidclosed_script_exists_and_is_valid():
    import os
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "lidclosed.sh"
    assert script.exists() and os.access(script, os.X_OK)
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_lidclosed_uses_pmset_not_caffeinate():
    """caffeinate blocks idle sleep but not lid-close sleep. Only pmset
    disablesleep changes that, which is why autostart.sh alone was not enough."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "lidclosed.sh").read_text()
    assert "pmset -a disablesleep 1" in src
    assert "pmset -a disablesleep 0" in src, "there must be a way back"


def test_lidclosed_warns_about_heat_and_can_be_reversed():
    """A laptop with sleep disabled inside a bag has no airflow. No software
    check can tell where the laptop is, so the warning has to be explicit."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "lidclosed.sh").read_text()
    assert "In a bag" in src and "cook" in src
    assert "AC Power" in src, "it must refuse quietly on battery"
    assert 'read -r -p "Type ' in src, "a system-wide change needs confirmation"
    assert "status" in src and "off" in src


# ------------------------------------------------------ server deployment

def test_deploy_script_is_valid_shell():
    import os
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "deploy_server.sh"
    assert script.exists() and os.access(script, os.X_OK)
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_deploy_tests_data_access_before_installing_anything():
    """Datacenter IPs get blocked by Yahoo far harder than home connections.
    That failure makes the whole migration pointless and is invisible until
    tested, so it must be tested first, not discovered afterwards."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "deploy_server.sh").read_text()
    assert src.index("probe_test") < src.index("pip install --quiet -r requirements"), (
        "the data-access check must run before the install work")
    assert "will not serve this address" in src
    assert "RELIANCE.NS" in src, "Indian tickers are blocked separately from US ones"


def test_deploy_probe_is_valid_python():
    import ast
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "deploy_server.sh").read_text()
    probe = re.search(r"cat > /tmp/probe_test\.py <<'PROBE'\n(.*?)\nPROBE", src, re.S)
    assert probe, "the embedded probe script is missing"
    ast.parse(probe.group(1))


def test_deploy_service_restarts_and_reads_credentials():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "scripts" / "deploy_server.sh").read_text()
    assert "Restart=always" in src, "a service that dies once must come back"
    assert "EnvironmentFile" in src, "systemd does not inherit a shell either"
    assert "autostart.sh remove" in src, "running two coordinators would double every send"


# ------------------------------------------------- state across processes

def test_status_can_see_what_the_daemon_did(tmp_path, monkeypatch):
    """Counters lived only in memory, so `--status` — a fresh process — always
    printed zeros regardless of what the daemon was doing. A status command
    that cannot see the running system is worse than none: it answers the
    question wrongly instead of admitting it cannot."""
    import asyncio
    from datetime import timedelta

    from sigbot.scheduler import Scheduler, Task

    monkeypatch.chdir(tmp_path)
    daemon = Scheduler()
    daemon.register(Task("demo", lambda: None, timedelta(seconds=1),
                         run_on_start=True))
    asyncio.run(daemon.run(poll_seconds=0.02, max_ticks=4))
    assert daemon.tasks[0].runs >= 1
    assert (tmp_path / "scheduler_state.json").exists()

    fresh = Scheduler()
    fresh.register(Task("demo", lambda: None, timedelta(seconds=1)))
    assert fresh.tasks[0].runs == 0
    assert fresh.load_state() is True
    assert fresh.tasks[0].runs == daemon.tasks[0].runs
    assert fresh.tasks[0].last_success is not None


def test_the_run_count_is_saved_after_it_increments(tmp_path, monkeypatch):
    """An earlier ordering saved before the increment, so the file said the
    daemon had never completed anything while it was working perfectly."""
    import asyncio
    import json
    from datetime import timedelta

    from sigbot.scheduler import Scheduler, Task

    monkeypatch.chdir(tmp_path)
    sched = Scheduler()
    sched.register(Task("demo", lambda: None, timedelta(seconds=1),
                        run_on_start=True))
    asyncio.run(sched.run(poll_seconds=0.02, max_ticks=4))

    saved = json.loads((tmp_path / "scheduler_state.json").read_text())
    assert saved["demo"]["runs"] == sched.tasks[0].runs >= 1


def test_no_state_file_is_reported_not_shown_as_zeros(tmp_path, monkeypatch):
    from datetime import timedelta

    from sigbot.scheduler import Scheduler, Task

    monkeypatch.chdir(tmp_path)
    sched = Scheduler()
    sched.register(Task("demo", lambda: None, timedelta(seconds=1)))
    assert sched.load_state() is False


def test_a_failure_is_persisted_too(tmp_path, monkeypatch):
    import asyncio
    import json
    from datetime import timedelta

    from sigbot.scheduler import Scheduler, Task

    monkeypatch.chdir(tmp_path)

    def boom():
        raise RuntimeError("down")

    sched = Scheduler()
    sched.register(Task("demo", boom, timedelta(seconds=1), run_on_start=True))
    asyncio.run(sched.run(poll_seconds=0.02, max_ticks=4))

    saved = json.loads((tmp_path / "scheduler_state.json").read_text())
    assert saved["demo"]["consecutive_failures"] >= 1
    assert saved["demo"]["runs"] == 0


# ------------------------------------------------ the gate that never opened

def test_a_task_without_run_on_start_still_runs(tmp_path, monkeypatch):
    """`due` returned run_on_start when last_attempt was None, and last_attempt
    is only set by running. So a task without the flag waited forever for a
    first run the gate would not grant.

    Six of eight jobs sat at "0 runs, last attempt never" for days — alive,
    scheduled, and silently never called. Only `resolve` escaped, because it
    happened to carry the flag."""
    import asyncio
    from datetime import timedelta

    from sigbot.scheduler import Scheduler, Task

    monkeypatch.chdir(tmp_path)
    ran: list[str] = []
    sched = Scheduler()
    sched.register(Task("eager", lambda: ran.append("eager"),
                        timedelta(seconds=0.05), run_on_start=True))
    sched.register(Task("patient", lambda: ran.append("patient"),
                        timedelta(seconds=0.05)))

    asyncio.run(sched.run(poll_seconds=0.02, max_ticks=15))

    assert ran.count("eager") >= 1
    assert ran.count("patient") >= 1, (
        "a task without run_on_start never ran at all")


def test_run_on_start_means_immediately_not_ever(tmp_path, monkeypatch):
    """The flag decides when the first run happens, not whether it happens."""
    from datetime import datetime, timedelta, timezone

    from sigbot.scheduler import Task

    monkeypatch.chdir(tmp_path)
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

    eager = Task("a", lambda: None, timedelta(minutes=30), run_on_start=True)
    assert eager.due(now) is True

    patient = Task("b", lambda: None, timedelta(minutes=30))
    assert patient.due(now) is False, "should wait one interval, not forever"
    assert patient.due(now + timedelta(minutes=31)) is True


def test_every_scheduled_job_can_reach_a_first_run(tmp_path, monkeypatch):
    """The regression that mattered: publish, daily, opportunities,
    day_summary, contagion and cycle all carried run_on_start=False."""
    from datetime import datetime, timedelta, timezone

    from sigbot.coordinator import JOBS
    from sigbot.scheduler import Task

    monkeypatch.chdir(tmp_path)
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

    for name, _attr, interval, _venue in JOBS:
        task = Task(name, lambda: None, interval)
        task.due(now)                       # sets first_seen
        assert task.due(now + interval + timedelta(seconds=1)) is True, (
            f"{name} can never reach a first run")


# ------------------------------------ a daily job inside a market window

def test_a_daily_job_runs_once_per_trading_day_not_every_24_hours():
    """Measuring 24 hours from the last attempt pins the next one to whatever
    time that was. A single run outside the window — manual, or after a restart
    — pins it outside the window permanently: it waits a day, misses again, and
    never catches up.

    That is what happened. A hand-run at 21:17 IST meant `daily` was next due
    at 21:17 IST, when NSE has been shut for six hours, every day thereafter."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from sigbot.market_hours import Venue
    from sigbot.scheduler import Task

    ist = ZoneInfo("Asia/Kolkata")
    task = Task("daily", lambda: None, timedelta(days=1), venue=Venue.NSE)
    task.last_attempt = datetime(2026, 9, 1, 21, 17, tzinfo=ist)

    during = datetime(2026, 9, 2, 11, 0, tzinfo=ist)
    assert task.due(during) is True, "should be due the next trading day"
    assert task.gated(during)[0] is True

    same_day = datetime(2026, 9, 1, 23, 0, tzinfo=ist)
    assert task.due(same_day) is False, "must not run twice in one trading day"


def test_a_daily_job_still_waits_for_its_venue():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from sigbot.market_hours import Venue
    from sigbot.scheduler import Task

    ist = ZoneInfo("Asia/Kolkata")
    task = Task("daily", lambda: None, timedelta(days=1), venue=Venue.NSE)
    task.last_attempt = datetime(2026, 9, 1, 11, 0, tzinfo=ist)

    after_close = datetime(2026, 9, 2, 21, 0, tzinfo=ist)
    assert task.due(after_close) is True
    assert task.gated(after_close)[0] is False, "due is not the same as allowed"


def test_sub_daily_jobs_keep_the_elapsed_time_rule():
    """Drift of a few seconds does not matter for a 20-minute job, and a
    calendar rule would make it run once a day."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from sigbot.scheduler import Task

    ist = ZoneInfo("Asia/Kolkata")
    task = Task("resolve", lambda: None, timedelta(minutes=20))
    task.last_attempt = datetime(2026, 9, 2, 11, 0, tzinfo=ist)

    assert task.due(datetime(2026, 9, 2, 11, 10, tzinfo=ist)) is False
    assert task.due(datetime(2026, 9, 2, 11, 25, tzinfo=ist)) is True


def test_the_trading_day_is_measured_in_the_venues_timezone():
    """A UTC date splits an Indian session: 09:15 IST is the previous UTC day,
    so a UTC-based rule would let `daily` run twice in one NSE session."""
    from datetime import datetime, timedelta, timezone

    from sigbot.market_hours import Venue
    from sigbot.scheduler import Task

    task = Task("daily", lambda: None, timedelta(days=1), venue=Venue.NSE)
    # 04:00 and 09:00 UTC are the same NSE day, either side of no UTC boundary,
    # but the check must use IST regardless.
    task.last_attempt = datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc)
    assert task.due(datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)) is False
