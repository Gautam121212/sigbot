"""Halt: wipe the loop and stop everything until resume."""
from __future__ import annotations

import sqlite3

from sigbot.shadow import ShadowLedger


def test_halt_wipes_and_stays_off(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "s.db")
    led = ShadowLedger(db)
    led.record("stocks", "AAPL", "BUY", 0.6, 0.02, 100.0)

    class S:
        shadow_db = db
    runner.run_halt(settings=S)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0
    assert runner.is_halted(), "stays halted with no auto-resume"


def test_resume_lifts_the_halt(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "s.db")
    ShadowLedger(db)

    class S:
        shadow_db = db
    runner.run_halt(settings=S)
    assert runner.is_halted()
    runner.run_resume(settings=S)
    assert not runner.is_halted(), "resume clears the halt"


def test_halt_backs_up_first(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "s.db")
    led = ShadowLedger(db)
    led.record("stocks", "AAPL", "BUY", 0.6, 0.02, 100.0)

    class S:
        shadow_db = db
    runner.run_halt(settings=S)
    assert list(tmp_path.glob("s.db.*.bak")), "the ledger is backed up before wiping"
