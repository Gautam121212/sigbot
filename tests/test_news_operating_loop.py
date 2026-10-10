"""News wired through OperatingLoop — the integration path:

    news scan (news_queue>0) -> scheduler emits PREDICT_CURRENT_SESSION
                             -> LiveHandlers.predict -> temp ledger 'news' row

Plus the failure invariants and the Option-A dedup rule:
  * empty queue records nothing (MONITOR, not PREDICT),
  * a scan exception returns no setups (no partial dispatch),
  * the same symbol+source within one UTC day records once, not twice.
All against a temporary database — never the production shadow.db.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from sigbot.shadow import ShadowLedger
from sigbot.live_handlers import LiveHandlers, RealSetupSources
from sigbot.operating_loop_v2 import OperatingLoop

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

# A fully-formed news setup as RealSetupSources.news() would emit: event_id is
# the Option-A SYMBOL:source:date key the NEWS handler needs for dedup.
QUALIFYING = {
    "symbol": "ACME", "side": "BUY", "score": 0.7, "expected_move": 0.05,
    "scan_price": 100.0, "horizon_hours": 24,
    "event_id": "ACME:reuters:20261011", "payload": '{"source": "reuters"}',
}


def _loop_with(tmp_path, setups):
    ledger = ShadowLedger(str(tmp_path / "l.db"))
    handlers = LiveHandlers(ledger=ledger, market=None, now_fn=lambda: NOW,
                            news_setups=lambda: list(setups))
    return OperatingLoop(handlers=handlers), ledger


def _news_rows(ledger):
    with closing(sqlite3.connect(ledger.path)) as con:
        return con.execute(
            "SELECT model, symbol, created_at, payload "
            "FROM predictions WHERE model='news'").fetchall()


def test_qualifying_news_setup_traverses_loop_to_ledger(tmp_path):
    """Positive path: a queued news event is persisted as a 'news' row carrying
    the event_id in its dedup key."""
    loop, ledger = _loop_with(tmp_path, [QUALIFYING])
    loop.tick(now=NOW, news_queue=1)
    rows = _news_rows(ledger)
    assert len(rows) == 1, f"expected one news row, got {rows}"
    model, symbol, created_at, payload = rows[0]
    assert model == "news"
    assert symbol == "ACME"
    assert created_at                                # persisted timestamp
    assert "ACME:reuters:20261011" in payload        # event_id in dedup key


def test_zero_news_queue_creates_no_prediction(tmp_path):
    """Empty queue -> scheduler emits MONITOR for news, never PREDICT, so the
    handler records nothing even with a setup available."""
    loop, ledger = _loop_with(tmp_path, [QUALIFYING])
    loop.tick(now=NOW, news_queue=0)
    assert _news_rows(ledger) == []


def test_same_day_same_source_dedups(tmp_path):
    """Option A: the same symbol+source+date records once across two ticks."""
    loop, ledger = _loop_with(tmp_path, [QUALIFYING])
    loop.tick(now=NOW, news_queue=1)
    loop.tick(now=NOW, news_queue=1)                 # identical event_id
    assert len(_news_rows(ledger)) == 1


def test_failed_scan_returns_no_setups(tmp_path, monkeypatch):
    """Fail-closed: run_news captures a candidate and then raises; news() must
    return [] so a partial, failed scan is never handed to the handler."""
    import sigbot.runner as R

    def boom(messenger=None, settings=None, hours=12):
        led = R.ShadowLedger(getattr(settings, "shadow_db", "shadow.db"))
        led.record("news", "PARTIAL", "BUY", 0.5, 0.05, 100.0, 24,
                   payload='{"source": "x"}', gate=True)
        raise RuntimeError("RSS fetch failed mid-scan")

    monkeypatch.setattr(R, "run_news", boom)

    class S:
        shadow_db = str(tmp_path / "l.db")

    assert RealSetupSources(settings=S()).news() == []
