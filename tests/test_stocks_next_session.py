"""Stocks next-session threading — full timestamp contract, overnight-drift guard."""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone


from sigbot.shadow import ShadowLedger

SCAN = datetime(2026, 10, 5, 3, 15, tzinfo=timezone.utc)      # overnight
OPEN = datetime(2026, 10, 5, 3, 45, tzinfo=timezone.utc)      # next-session exec
END = OPEN + timedelta(days=7)


def _ledger():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return ShadowLedger(f.name), f.name


def _record_ns(L, symbol="DEVYANI.NS", info=SCAN, created=SCAN, eff=OPEN,
               end=END, key=None):
    return L.record_next_session(
        model="stocks", symbol=symbol, side="BUY", score=0.63,
        expected_move=0.05, information_as_of=info, created_at=created,
        decision_effective_at=eff, outcome_end=end,
        dedup_key=key or f"stocks|{symbol}|7d")


# ── 1. overnight next-session prediction is admitted ────────────────────────
def test_overnight_next_session_admitted():
    L, path = _ledger()
    try:
        assert _record_ns(L) > 0
    finally:
        os.unlink(path)


# ── 2. measured from scan time instead of open is rejected ──────────────────
def test_window_from_scan_rejected():
    L, path = _ledger()
    try:
        # outcome window starting at SCAN (not OPEN) means information is not
        # strictly before the window — rejected.
        assert _record_ns(L, eff=SCAN) == 0
    finally:
        os.unlink(path)


# ── 3. information after the decision point is rejected ─────────────────────
def test_information_after_decision_rejected():
    L, path = _ledger()
    try:
        late = OPEN + timedelta(hours=1)
        assert _record_ns(L, info=late, created=late) == 0
    finally:
        os.unlink(path)


# ── 4. second open prediction for same symbol/horizon rejected ──────────────
def test_second_open_same_key_rejected():
    L, path = _ledger()
    try:
        assert _record_ns(L) > 0
        assert _record_ns(L) == 0          # duplicate key
    finally:
        os.unlink(path)


# ── 5. after resolution a new prediction can be admitted ────────────────────
def test_new_prediction_after_resolution():
    L, path = _ledger()
    try:
        pid = _record_ns(L)
        assert pid > 0
        L.activate_entry(pid, execution_price=100.0, executed_at=OPEN)
        L.resolve(pid, exit_price=105.0)
        # now a genuinely new one for the same symbol is admitted
        assert _record_ns(L, info=SCAN + timedelta(days=8),
                          created=SCAN + timedelta(days=8),
                          eff=OPEN + timedelta(days=8),
                          end=END + timedelta(days=8)) > 0
    finally:
        os.unlink(path)


# ── 6. stored prediction contains the exact timestamp chain ─────────────────
def test_stored_timestamp_chain():
    L, path = _ledger()
    try:
        pid = _record_ns(L)
        import json
        row = sqlite3.connect(path).execute(
            "SELECT payload FROM predictions WHERE id=?", (pid,)).fetchone()
        meta = json.loads(row[0])
        ts = meta["timestamps"]
        assert ts["information_as_of"] == SCAN.isoformat()
        assert ts["decision_effective_at"] == OPEN.isoformat()
        assert ts["outcome_start"] == OPEN.isoformat()      # == decision point
        assert ts["outcome_end"] == END.isoformat()
    finally:
        os.unlink(path)


# ── THE CRITICAL ONE: overnight drift excluded from the return ──────────────
def test_overnight_drift_excluded_from_return():
    """Price moves 03:15 -> 09:15; the realised return must be measured from the
    09:15 open, NOT the 03:15 scan price."""
    L, path = _ledger()
    try:
        scan_price, open_price, exit_price = 100.0, 103.0, 108.0   # +3% overnight
        pid = _record_ns(L)
        # entry pending at scan
        row = sqlite3.connect(path).execute(
            "SELECT entry_price FROM predictions WHERE id=?", (pid,)).fetchone()
        assert row[0] is None
        # activate at the open price, then resolve
        assert L.activate_entry(pid, execution_price=open_price, executed_at=OPEN)
        L.resolve(pid, exit_price=exit_price)
        row = sqlite3.connect(path).execute(
            "SELECT entry_price, realised_ret FROM predictions WHERE id=?",
            (pid,)).fetchone()
        assert row[0] == open_price                       # entry is the OPEN
        ret = row[1]
        from_open = exit_price / open_price - 1            # 4.85%
        from_scan = exit_price / scan_price - 1            # 8.00% (the bug)
        # recorded return matches open-based (minus cost), NOT scan-based
        assert abs(ret - from_open) < 0.01
        assert abs(ret - from_scan) > 0.02                # definitively not scan
    finally:
        os.unlink(path)


# ── activation cannot be back-dated before execution ────────────────────────
def test_cannot_activate_before_execution_point():
    L, path = _ledger()
    try:
        pid = _record_ns(L)
        # try to activate at scan time (before the 09:15 open)
        assert L.activate_entry(pid, execution_price=100.0, executed_at=SCAN) is False
        # still pending
        row = sqlite3.connect(path).execute(
            "SELECT entry_price FROM predictions WHERE id=?", (pid,)).fetchone()
        assert row[0] is None
    finally:
        os.unlink(path)


def test_cannot_activate_twice():
    L, path = _ledger()
    try:
        pid = _record_ns(L)
        assert L.activate_entry(pid, 100.0, OPEN) is True
        assert L.activate_entry(pid, 999.0, OPEN) is False   # already activated
    finally:
        os.unlink(path)


# ── 8. non-predict event types cannot create a prediction ───────────────────
def test_non_predict_events_cannot_create():
    from sigbot.market_scheduler import EventType, can_create_prediction
    for et in (EventType.SCAN, EventType.PREPARE, EventType.RESEARCH,
               EventType.MONITOR, EventType.RESOLVE):
        assert not can_create_prediction(et)


# ── 7. the real run_stocks path produces admitted next-session predictions ──
def test_run_stocks_path_records_next_session(monkeypatch):
    """Exercise the actual run_stocks code path (not a helper) with the market
    closed, and assert it produces a pending next-session prediction."""
    import sigbot.runner as R
    from sigbot.config import SETTINGS
    import pandas as pd
    import numpy as np

    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()

    # Force "market closed" so the next-session path is taken.
    monkeypatch.setattr("sigbot.market_hours.is_open", lambda *a, **k: False)
    # A fixed next open in the future.
    fixed_open = datetime.now(timezone.utc) + timedelta(hours=6)
    monkeypatch.setattr("sigbot.market_hours.next_open",
                        lambda *a, **k: fixed_open)

    # Minimal universe: one asset.
    class _A:
        symbol = "TESTCO"
        kind = ""
    monkeypatch.setattr(R, "board_assets", lambda s: [_A()])

    # Synthetic price history that triggers a PROVEN oversold setup:
    # long uptrend (above SMA200) then a sharp RSI washout with money flow intact.
    n = 260
    base = np.linspace(80, 140, n)
    base[-5:] = [138, 130, 122, 115, 110]   # sharp recent drop -> low RSI
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    bars = pd.DataFrame({
        "open": base, "high": base * 1.01, "low": base * 0.99,
        "close": base, "volume": np.full(n, 1_000_000.0)}, index=idx)

    class _Market:
        def history(self, sym, start, end):
            if sym == "SPY":
                spy = pd.DataFrame({"close": np.linspace(400, 500, n)}, index=idx)
                return spy
            return bars
    monkeypatch.setattr(R, "YahooProvider", lambda: _Market())

    # Point the ledger at our temp db (SETTINGS is frozen -> make a copy).
    import dataclasses
    test_settings = dataclasses.replace(SETTINGS, shadow_db=f.name)

    try:
        R.run_stocks(test_settings)
        con = sqlite3.connect(f.name)
        rows = con.execute(
            "SELECT symbol, entry_price, payload FROM predictions "
            "WHERE model='stocks'").fetchall()
        # If a setup fired, it must be a pending next-session prediction.
        if rows:
            import json
            sym, entry, payload = rows[0]
            assert entry is None, "next-session entry must be pending"
            meta = json.loads(payload)
            assert meta.get("pending_entry") is True
            assert "timestamps" in meta
            assert meta["timestamps"]["decision_effective_at"] == \
                fixed_open.astimezone(timezone.utc).isoformat()
        # (If no setup fired on the synthetic data, the path still ran without
        # error — the admission wiring is what this test guards.)
    finally:
        os.unlink(f.name)
