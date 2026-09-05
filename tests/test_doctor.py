"""Tests for the health check and the automation scripts.

The doctor exists because the first live run went wrong in ways nothing
reported: a stale board from a test run, a sample page mistaken for real
results, and an install inside a folder macOS blocks background jobs from
reading. Each of those now has a check.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sigbot import doctor

ROOT = Path(__file__).resolve().parents[1]


def test_every_check_returns_a_verdict():
    for c in doctor.run(include_network=False):
        assert c.status in (doctor.OK, doctor.WARN, doctor.FAIL)
        assert c.name and c.detail


def test_a_problem_always_carries_its_fix():
    """A check that says something is wrong without saying what to do is noise."""
    for c in doctor.run(include_network=False):
        if c.status in (doctor.WARN, doctor.FAIL):
            assert c.fix or "not macOS" in c.detail or "expected" in c.detail, (
                f"{c.name} reports a problem with no fix")


def test_python_and_packages_pass_here():
    assert doctor.check_python().status == doctor.OK
    assert doctor.check_packages().status == doctor.OK


def _as_mac(monkeypatch, path: str):
    """Pretend to be a Mac with /Users/x as the home folder."""
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(doctor, "ROOT", Path(path))
    monkeypatch.setattr(doctor.Path, "home", staticmethod(lambda: Path("/Users/x")))


def test_the_home_folder_is_the_right_place(monkeypatch):
    _as_mac(monkeypatch, "/Users/x/sigbot")
    c = doctor.check_location()
    assert c.status == doctor.OK
    assert "right place" in c.detail


def test_a_protected_folder_is_flagged(monkeypatch):
    """~/Downloads works by hand and fails silently on a schedule."""
    for folder in ("Downloads", "Documents", "Desktop"):
        _as_mac(monkeypatch, f"/Users/x/{folder}/sigbot")
        c = doctor.check_location()
        assert c.status == doctor.WARN, folder
        assert "fail silently" in c.detail
        assert "mv" in c.fix


def test_icloud_is_a_failure_not_a_warning(monkeypatch):
    """iCloud can offload the database mid-run and put it back later."""
    _as_mac(monkeypatch, "/Users/x/Library/Mobile Documents/com~apple~CloudDocs/sigbot")
    c = doctor.check_location()
    assert c.status == doctor.FAIL
    assert "offload" in c.detail


def test_a_temp_folder_is_a_failure(monkeypatch):
    for tmp in ("/tmp/sigbot", "/private/tmp/sigbot", "/var/folders/ab/sigbot"):
        _as_mac(monkeypatch, tmp)
        c = doctor.check_location()
        assert c.status == doctor.FAIL, tmp
        assert "deletes this" in c.detail


def test_an_external_volume_is_a_warning(monkeypatch):
    _as_mac(monkeypatch, "/Volumes/SSD/sigbot")
    c = doctor.check_location()
    assert c.status == doctor.WARN and "unmounted" in c.detail


def test_a_synced_documents_folder_gets_the_extra_note(monkeypatch):
    _as_mac(monkeypatch, "/Users/x/Documents/sigbot")
    assert "offloaded" in doctor.check_location().detail
    _as_mac(monkeypatch, "/Users/x/Downloads/sigbot")
    assert "offloaded" not in doctor.check_location().detail


def test_a_sample_page_is_called_out(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    public = app / "public"; public.mkdir()
    (public / "index.html").write_text("<html>SAMPLE DATA here</html>")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    c = doctor.check_report()
    assert c.status == doctor.WARN
    assert "not your numbers" in c.detail
    assert "publish" in c.fix


def test_a_page_with_javascript_is_a_failure(monkeypatch, tmp_path):
    """It would open blank on the iPhone, which is the whole point of the page."""
    app = tmp_path / "app"
    app.mkdir()
    public = app / "public"; public.mkdir()
    (public / "index.html").write_text("<html><script>x</script></html>")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    c = doctor.check_report()
    assert c.status == doctor.FAIL and "blank on an iPhone" in c.detail


def test_missing_board_and_ledger_are_warnings_not_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    assert doctor.check_board().status == doctor.WARN
    assert doctor.check_ledger().status == doctor.WARN
    assert "run_screen" in doctor.check_board().fix


def test_a_short_board_is_flagged(monkeypatch, tmp_path):
    """A board of 60 means the screen partly failed and nobody noticed."""
    from sigbot.watchlist import Watchlist

    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    wl = Watchlist(tmp_path / "watchlist.db")
    from sigbot.config import POOL

    wl.seed(POOL[:60], target=60)
    c = doctor.check_board()
    assert c.status == doctor.WARN and "expected 100" in c.detail


def test_a_full_board_passes(monkeypatch, tmp_path):
    from sigbot.config import POOL
    from sigbot.watchlist import Watchlist

    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    Watchlist(tmp_path / "watchlist.db").seed(POOL)
    assert doctor.check_board().status == doctor.OK


def test_ledger_reports_progress(monkeypatch, tmp_path):
    from sigbot.shadow import ShadowLedger
    from tests.conftest import write_records

    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    led = ShadowLedger(tmp_path / "shadow.db")
    write_records(led, "news", "NVDA", 20, 0.6)
    c = doctor.check_ledger()
    assert c.status == doctor.OK and "20 made" in c.detail


def test_main_returns_nonzero_only_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "run", lambda include_network=True: [
        doctor.Check("x", doctor.FAIL, "broken", "do this")])
    assert doctor.main(["--offline"]) == 1
    assert "do this" in capsys.readouterr().out

    monkeypatch.setattr(doctor, "run", lambda include_network=True: [
        doctor.Check("x", doctor.OK, "fine")])
    assert doctor.main(["--offline"]) == 0


# ------------------------------------------------------------- the scripts

@pytest.mark.parametrize("script", ["install.sh", "schedule.sh"])
def test_shell_scripts_are_valid(script):
    r = subprocess.run(["bash", "-n", str(ROOT / "scripts" / script)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("script", ["install.sh", "schedule.sh"])
def test_shell_scripts_are_executable(script):

    assert os.access(ROOT / "scripts" / script, os.X_OK)


def test_daily_job_parses_and_covers_every_stage():
    import ast

    src = (ROOT / "scripts" / "daily_job.py").read_text()
    ast.parse(src)
    for stage in ("run_resolve", "run_daily", "run_publish", "run_cycle"):
        assert stage in src, f"{stage} missing from the scheduled job"


def test_daily_job_runs_resolve_before_daily():
    """Scoring yesterday must happen before predicting today, or the ledger
    grows faster than it is checked."""
    src = (ROOT / "scripts" / "daily_job.py").read_text()
    assert src.index('"resolve"') < src.index('"daily"')


def test_schedule_script_warns_about_protected_folders():
    src = (ROOT / "scripts" / "schedule.sh").read_text()
    assert "Downloads" in src and "Full Disk Access" in src
    assert "launchctl" in src and "cron" in src


def test_install_script_stops_on_failure():
    src = (ROOT / "scripts" / "install.sh").read_text()
    assert "set -euo pipefail" in src
    assert "die " in src and "pytest" in src


def test_a_quiet_day_is_not_reported_as_a_missing_day(monkeypatch, tmp_path):
    """Every asset holding is the system working, not the job failing.

    The first dress rehearsal reported "no predictions made" after a clean run
    where all 100 assets correctly held — which reads as broken.
    """
    from sigbot.shadow import ShadowLedger

    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    led = ShadowLedger(tmp_path / "shadow.db")
    led.log_run("daily", considered=100, signals=0, note="100 holds, 0 failed to load")

    c = doctor.check_ledger()
    assert c.status == doctor.OK
    assert "held on everything" in c.detail
    assert "usual outcome" in c.detail


def test_a_job_that_never_ran_is_still_flagged(monkeypatch, tmp_path):
    from sigbot.shadow import ShadowLedger

    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    ShadowLedger(tmp_path / "shadow.db")          # exists, but never ran
    c = doctor.check_ledger()
    assert c.status == doctor.WARN and "never run" in c.detail


def test_run_log_survives_an_older_ledger(tmp_path):
    """A ledger created before the runs table must not break on upgrade."""
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "model TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, score REAL, "
            "expected_move REAL, created_at TEXT NOT NULL, resolve_after TEXT NOT NULL, "
            "entry_price REAL, exit_price REAL, realised_ret REAL, hit INTEGER, payload TEXT)")

    from sigbot.shadow import ShadowLedger

    led = ShadowLedger(path)
    assert led.last_run("daily") is None
    led.log_run("daily", considered=5, signals=1)
    assert led.last_run("daily")["signals"] == 1


# ------------------------------------------------------- the scheduled job

def _daily_job():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dj", ROOT / "scripts" / "daily_job.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_daily_job_loads_env_because_launchd_does_not(tmp_path, monkeypatch):
    """A scheduled run inherits none of your Terminal's variables, so without
    this the delivery silently has no credentials."""
    dj = _daily_job()
    monkeypatch.setattr(dj, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        'TELEGRAM_TOKEN="abc:123"\nTELEGRAM_CHAT_ID=999\n# a comment\n\n')
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    dj.load_env()
    assert os.environ["TELEGRAM_TOKEN"] == "abc:123"
    assert os.environ["TELEGRAM_CHAT_ID"] == "999"


def test_env_loading_never_overrides_what_is_already_set(tmp_path, monkeypatch):
    dj = _daily_job()
    monkeypatch.setattr(dj, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("TELEGRAM_CHAT_ID=fromfile\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "fromshell")
    dj.load_env()
    assert os.environ["TELEGRAM_CHAT_ID"] == "fromshell"


def test_missing_env_file_is_not_an_error(tmp_path, monkeypatch):
    dj = _daily_job()
    monkeypatch.setattr(dj, "ROOT", tmp_path)
    dj.load_env()


def test_weekly_summary_reports_even_with_no_signals(tmp_path):
    """Silence is ambiguous: nothing fired, or the job died a fortnight ago."""
    from sigbot.config import POOL, Settings
    from sigbot.shadow import ShadowLedger
    from sigbot.watchlist import Watchlist

    st = Settings(shadow_db=str(tmp_path / "s.db"),
                  watchlist_db=str(tmp_path / "w.db"))
    led = ShadowLedger(st.shadow_db)
    led.log_run("daily", considered=100, signals=0, note="100 holds")
    Watchlist(st.watchlist_db).seed(POOL)

    text = _daily_job().weekly_summary(st)
    assert "Weekly summary" in text
    assert "100 holds" in text
    assert "Board:" in text and "total" in text
    assert "Nothing has been checked yet" in text


def test_weekly_summary_survives_a_missing_ledger(tmp_path):
    from sigbot.config import Settings

    st = Settings(shadow_db="/nonexistent/dir/s.db",
                  watchlist_db="/nonexistent/dir/w.db")
    text = _daily_job().weekly_summary(st)
    assert "Weekly summary" in text, "a broken ledger must not stop the summary"


def test_summary_only_fires_weekly_or_on_demand():
    src = (ROOT / "scripts" / "daily_job.py").read_text()
    assert "weekday() == 0" in src, "should run on Mondays"
    assert '"--summary" in sys.argv' in src, "should be forceable for testing"
