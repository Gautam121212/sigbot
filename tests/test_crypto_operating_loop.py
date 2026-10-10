"""Crypto wired through OperatingLoop — the integration path:

    crypto scan -> scheduler emits PREDICT_CURRENT_SESSION (crypto_open, always)
                -> LiveHandlers.predict -> temp ledger 'crypto' row

Plus the failure invariants and the signal_instance dedup rule:
  * no setups records nothing,
  * a scan exception returns no setups (no partial dispatch),
  * the same coiled signal records once (open-key guard), not once per tick.
All against a temporary database — never the production shadow.db.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from sigbot.shadow import ShadowLedger
from sigbot.live_handlers import LiveHandlers, RealSetupSources
from sigbot.operating_loop_v2 import OperatingLoop

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)   # crypto is 24/7 -> open

# A crypto setup as RealSetupSources.crypto() emits it: signal_instance is the
# stable signal-class identity the handler folds into its dedup key.
QUALIFYING = {
    "symbol": "BTC", "side": "MOVE", "score": 0.7, "expected_move": 0.10,
    "scan_price": 50000.0, "horizon_hours": 72,
    "payload": "coiled-spring: calm+volume", "signal_instance": "coiled-spring",
}


def _loop_with(tmp_path, setups):
    ledger = ShadowLedger(str(tmp_path / "l.db"))
    handlers = LiveHandlers(ledger=ledger, market=None, now_fn=lambda: NOW,
                            crypto_setups=lambda: list(setups))
    return OperatingLoop(handlers=handlers), ledger


def _crypto_rows(ledger):
    with closing(sqlite3.connect(ledger.path)) as con:
        return con.execute(
            "SELECT model, symbol, created_at, payload "
            "FROM predictions WHERE model='crypto'").fetchall()


def test_qualifying_crypto_setup_traverses_loop_to_ledger(tmp_path):
    """Positive path: a coiled-spring signal is persisted as a 'crypto' row
    carrying the signal-class dedup key."""
    loop, ledger = _loop_with(tmp_path, [QUALIFYING])
    loop.tick(now=NOW)
    rows = _crypto_rows(ledger)
    assert len(rows) == 1, f"expected one crypto row, got {rows}"
    model, symbol, created_at, payload = rows[0]
    assert model == "crypto"
    assert symbol == "BTC"
    assert created_at                                       # persisted timestamp
    assert "crypto|BTC|72h|coiled-spring" in payload        # signal_instance key


def test_no_crypto_setups_creates_no_prediction(tmp_path):
    """Crypto fires every tick, but an empty setup list records nothing."""
    loop, ledger = _loop_with(tmp_path, [])
    loop.tick(now=NOW)
    assert _crypto_rows(ledger) == []


def test_repeated_signal_dedups(tmp_path):
    """signal_instance: the same coiled coin observed on two ticks records once
    (the open prediction suppresses the re-observation)."""
    loop, ledger = _loop_with(tmp_path, [QUALIFYING])
    loop.tick(now=NOW)
    loop.tick(now=NOW)                                       # same signal again
    assert len(_crypto_rows(ledger)) == 1


def test_failed_scan_returns_no_setups(tmp_path, monkeypatch):
    """Fail-closed: run_crypto_live captures a candidate and then raises;
    crypto() must return [] so a partial, failed scan never reaches the handler."""
    import sigbot.run_crypto_live as rc

    def boom(settings=None, provider=None, ledger=None, inter_request_sleep=2.5):
        ledger.record(model="crypto", symbol="PARTIAL", side="MOVE", score=0.5,
                      expected_move=0.10, entry_price=100.0, horizon_hours=72,
                      payload="coiled-spring: x", gate=True)
        raise RuntimeError("CoinGecko 429 mid-scan")

    monkeypatch.setattr(rc, "run_crypto_live", boom)

    class S:
        shadow_db = str(tmp_path / "l.db")

    assert RealSetupSources(settings=S()).crypto() == []
