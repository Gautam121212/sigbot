"""Fresh-start: remove corrupt rows, pause everything, keep the learning record."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from sigbot.shadow import ShadowLedger


def test_corrupt_rows_are_removed_but_real_ones_kept(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "s.db")
    led = ShadowLedger(db)
    # A real trade, a huge-move corrupt one, a null-entry one, a micro-price one.
    good = led.record("stocks", "AAPL", "BUY", 0.6, 0.02, 100.0)
    led.resolve(good, 103.0)                        # +3%, real
    bad1 = led.record("crypto15m", "U-USD", "BUY", 0.6, 0.02, 1e-6)
    led.resolve(bad1, 9.9e-8)                       # -90%, corrupt
    con = sqlite3.connect(db)
    con.execute("INSERT INTO predictions(model,symbol,side,score,expected_move,"
                "entry_price,created_at,resolve_after,hit) VALUES "
                "('news','X','BUY',0.5,0.0,NULL,?,?,1)",
                (datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()))
    con.commit()

    class S:
        shadow_db = db
    runner.run_fresh_start(settings=S)

    con = sqlite3.connect(db)
    rows = con.execute("SELECT symbol FROM predictions").fetchall()
    syms = {r[0] for r in rows}
    assert "AAPL" in syms, "the real trade is kept"
    assert "U-USD" not in syms, "the impossible-move row is removed"
    assert "X" not in syms, "the null-entry row is removed"


def test_fresh_start_writes_a_pause_marker(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "s.db")
    ShadowLedger(db)

    class S:
        shadow_db = db
    runner.run_fresh_start(settings=S)
    assert (tmp_path / runner.PAUSE_MARKER).exists()
    paused, _ = runner.is_paused()
    assert paused, "the model is paused after a fresh start"


def test_pause_lifts_after_its_time(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    from pathlib import Path
    # A marker in the past -> not paused.
    Path(runner.PAUSE_MARKER).write_text("2020-01-01T00:00:00+00:00")
    paused, _ = runner.is_paused()
    assert not paused, "an expired pause lifts automatically"


def test_wipe_needs_confirmation(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SIGBOT_CONFIRM_RESET", raising=False)
    db = str(tmp_path / "s.db")
    led = ShadowLedger(db)
    led.record("stocks", "AAPL", "BUY", 0.6, 0.02, 100.0)

    class S:
        shadow_db = db
    runner.run_wipe_and_pause(settings=S)   # no confirm -> refuses
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1, \
        "without confirmation, nothing is wiped"
