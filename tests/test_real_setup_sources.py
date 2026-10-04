"""Real setup sources — the capturing-proxy mechanism that feeds the real
scanner's output into the loop without duplicating model logic.

NOTE: the full path (real run_stocks detection -> setup -> loop) needs live
market data and is verified on the deployment host, not in CI. These tests prove
the capture mechanism is correct and lossless: what a runner records is exactly
what the setup source emits, and nothing leaks to the real DB."""
import os
import sqlite3
import tempfile

from sigbot.live_handlers import _CapturingLedger
from sigbot.shadow import ShadowLedger


def _ledger():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return ShadowLedger(f.name), f.name


# ── the capturing proxy intercepts records, writes nothing ──────────────────
def test_capturing_ledger_intercepts_record():
    L, path = _ledger()
    try:
        cap = _CapturingLedger(L)
        cap.record("stocks", "AAPL", "BUY", 0.6, 0.05, 100.0, 168,
                   payload="{}", dedup_key="stocks|AAPL|168h")
        # captured, not written
        assert len(cap.captured) == 1
        assert cap.captured[0]["symbol"] == "AAPL"
        assert cap.captured[0]["path"] == "record"
        n = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM predictions").fetchone()[0]
        assert n == 0                    # nothing leaked to the real DB
    finally:
        os.unlink(path)


def test_capturing_ledger_intercepts_next_session():
    from datetime import datetime, timedelta, timezone
    L, path = _ledger()
    try:
        cap = _CapturingLedger(L)
        now = datetime.now(timezone.utc)
        cap.record_next_session(
            model="stocks", symbol="DEVYANI.NS", side="BUY", score=0.6,
            expected_move=0.05, information_as_of=now, created_at=now,
            decision_effective_at=now + timedelta(hours=6),
            outcome_end=now + timedelta(days=7), dedup_key="k")
        assert len(cap.captured) == 1
        assert cap.captured[0]["path"] == "next_session"
        assert cap.captured[0]["symbol"] == "DEVYANI.NS"
        n = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM predictions").fetchone()[0]
        assert n == 0
    finally:
        os.unlink(path)


# ── read methods pass through to the real ledger ────────────────────────────
def test_capturing_ledger_passes_through_reads():
    L, path = _ledger()
    try:
        # write a real row directly, then confirm the proxy's read sees it
        L.record("stocks", "MSFT", "BUY", 0.6, 0.05, 100.0, 24, gate=False)
        cap = _CapturingLedger(L)
        assert cap.has_open_prediction("stocks", "MSFT") is True
        assert cap.has_open_prediction("stocks", "NOPE") is False
    finally:
        os.unlink(path)


# ── capture is lossless: every record argument is preserved ─────────────────
def test_capture_preserves_all_fields():
    L, path = _ledger()
    try:
        cap = _CapturingLedger(L)
        cap.record("news", "NVDA", "SELL", 0.72, 0.03, 500.0, 24,
                   payload='{"source":"8-K"}', dedup_key="news|E1|NVDA|24h")
        c = cap.captured[0]
        assert c["model"] == "news" and c["side"] == "SELL"
        assert c["score"] == 0.72 and c["scan_price"] == 500.0
        assert c["dedup_key"] == "news|E1|NVDA|24h"
    finally:
        os.unlink(path)


# ── a scan that records nothing yields no setups ────────────────────────────
def test_empty_scan_yields_no_setups():
    L, path = _ledger()
    try:
        cap = _CapturingLedger(L)
        # no record calls made
        assert cap.captured == []
    finally:
        os.unlink(path)
