"""Ventures wired through OperatingLoop — the integration path the direct
run_ventures_live tests do not cover:

    qualifying setup -> scheduler emits PREDICT_NEXT_SESSION (backlog>0)
                     -> LiveHandlers.predict -> temp ledger records a ventures row

Plus the two failure invariants: zero backlog creates no prediction, and a
scan that raises returns no setups (no partial dispatch). All against a
temporary database — never the production shadow.db.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from sigbot.shadow import ShadowLedger
from sigbot.live_handlers import LiveHandlers, RealSetupSources
from sigbot.operating_loop_v2 import OperatingLoop

# A Sunday noon UTC: all equity venues closed, so the tick's outcome for
# ventures depends only on the backlog we pass, not on session state.
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

QUALIFYING = {
    "symbol": "ACME", "side": "BUY", "score": 0.8, "expected_move": 0.20,
    "horizon_hours": 2160, "thesis_id": "acme-sustained-inflection",
    "payload": "",
}


def _loop_with(tmp_path, setups):
    ledger = ShadowLedger(str(tmp_path / "l.db"))
    handlers = LiveHandlers(ledger=ledger, market=None, now_fn=lambda: NOW,
                            ventures_setups=lambda: list(setups))
    return OperatingLoop(handlers=handlers), ledger


def _ventures_rows(ledger):
    with closing(sqlite3.connect(ledger.path)) as con:
        return con.execute(
            "SELECT model, symbol, created_at, resolve_after, payload "
            "FROM predictions WHERE model='ventures'").fetchall()


def test_qualifying_setup_traverses_loop_to_ledger(tmp_path):
    """Positive path: one qualifying thesis is persisted as a ventures row with
    correct model, symbol, a persisted timestamp, a forward resolve time, and
    the thesis identifier carried in the dedup key."""
    loop, ledger = _loop_with(tmp_path, [QUALIFYING])
    loop.tick(now=NOW, ventures_backlog=1)

    rows = _ventures_rows(ledger)
    assert len(rows) == 1, f"expected exactly one ventures row, got {rows}"
    model, symbol, created_at, resolve_after, payload = rows[0]
    assert model == "ventures"
    assert symbol == "ACME"
    assert created_at                                   # persisted timestamp
    assert resolve_after and resolve_after > created_at  # horizon points forward
    assert "acme-sustained-inflection" in payload        # thesis id in dedup key


def test_zero_backlog_creates_no_prediction(tmp_path):
    """Even with a qualifying setup available, backlog=0 must stop the scheduler
    from emitting a ventures PREDICT event, so nothing is recorded."""
    loop, ledger = _loop_with(tmp_path, [QUALIFYING])
    loop.tick(now=NOW, ventures_backlog=0)
    assert _ventures_rows(ledger) == []


def test_failed_scan_returns_no_setups(tmp_path, monkeypatch):
    """Fail-closed: if run_ventures_live captures a candidate and then raises,
    RealSetupSources.ventures() must return [] — a partial, failed scan is never
    handed on as if it completed."""
    import sigbot.run_ventures_live as rv

    def boom(settings=None, sec=None, price_of=None, ledger=None):
        ledger.record(model="ventures", symbol="PARTIAL", side="BUY",
                      score=0.5, expected_move=0.2, entry_price=10.0,
                      horizon_hours=2160, payload="", gate=True)
        raise RuntimeError("SEC timeout mid-scan")

    monkeypatch.setattr(rv, "run_ventures_live", boom)

    class S:
        shadow_db = str(tmp_path / "l.db")

    assert RealSetupSources(settings=S()).ventures() == []
