"""Purge-stale removes predictions from replaced model versions, keeps current ones."""
from __future__ import annotations

import sqlite3

from sigbot.shadow import ShadowLedger


def test_stale_crypto_and_news_removed_current_kept(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "s.db")
    led = ShadowLedger(db)
    # Old crypto: 1-2h horizon (Binance). New crypto would be 24h.
    old_crypto = led.record("crypto15m", "BTC", "BUY", 0.6, 0.02, 100.0, horizon_hours=1)
    led.resolve(old_crypto, 101.0)
    # A daily row (current model, 24h) — must be kept.
    daily = led.record("daily", "AAPL", "BUY", 0.6, 0.02, 100.0, horizon_hours=24)
    led.resolve(daily, 101.0)
    # An old news row with a negative score (pre-fix scoring) — must go.
    con = sqlite3.connect(db)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    con.execute("INSERT INTO predictions(model,symbol,side,score,expected_move,"
                "entry_price,created_at,resolve_after,hit) VALUES "
                "('news','X','BUY',-0.3,0.0,100.0,?,?,1)", (now, now))
    con.commit()

    class S:
        shadow_db = db
    runner.run_purge_stale(settings=S)

    con = sqlite3.connect(db)
    models = {r[0]: r[1] for r in con.execute(
        "SELECT model, COUNT(*) FROM predictions GROUP BY model")}
    assert models.get("crypto15m", 0) == 0, "stale 15-min crypto removed"
    assert models.get("news", 0) == 0, "negative-score news removed"
    assert models.get("daily", 0) == 1, "current daily kept"


def test_purge_backs_up_first(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "s.db")
    ShadowLedger(db)

    class S:
        shadow_db = db
    runner.run_purge_stale(settings=S)
    backups = list(tmp_path.glob("s.db.*.bak"))
    assert backups, "a backup is written before purging"
