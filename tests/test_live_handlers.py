"""Live activation handler — real ledger, overnight-drift exclusion, lineage."""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd

from sigbot.live_handlers import LiveActivationHandler
from sigbot.market_scheduler import Family
from sigbot.shadow import ShadowLedger

SCAN = datetime(2026, 10, 5, 3, 15, tzinfo=timezone.utc)
OPEN = datetime(2026, 10, 5, 3, 45, tzinfo=timezone.utc)
END = OPEN + timedelta(days=7)


class _Market:
    def __init__(self, open_price=103.0):
        self.open_price = open_price

    def history(self, sym, start, end):
        return pd.DataFrame({"open": [self.open_price], "high": [self.open_price + 1],
                             "low": [self.open_price - 1],
                             "close": [self.open_price + 0.5], "volume": [1e6]})


class _EmptyMarket:
    def history(self, sym, start, end):
        return pd.DataFrame()           # session not open / no data yet


def _ledger_with_pending():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    L = ShadowLedger(f.name)
    pid = L.record_next_session(
        model="stocks", symbol="DEVYANI.NS", side="BUY", score=0.63,
        expected_move=0.05, information_as_of=SCAN, created_at=SCAN,
        decision_effective_at=OPEN, outcome_end=END,
        dedup_key="stocks|DEVYANI.NS|7d")
    return L, f.name, pid


# ── pending query ───────────────────────────────────────────────────────────
def test_pending_entries_found():
    L, path, pid = _ledger_with_pending()
    try:
        pending = L.pending_entries("stocks")
        assert len(pending) == 1
        assert pending[0]["id"] == pid
        assert pending[0]["decision_effective_at"] == OPEN.isoformat()
    finally:
        os.unlink(path)


# ── activation at the session open ──────────────────────────────────────────
def test_activation_fills_open_price():
    L, path, pid = _ledger_with_pending()
    try:
        h = LiveActivationHandler(ledger=L, market=_Market(103.0),
                                  now_fn=lambda: OPEN + timedelta(minutes=1))
        assert h.activate_pending(Family.STOCKS, "RUN-1") == 1
        row = sqlite3.connect(path).execute(
            "SELECT entry_price FROM predictions WHERE id=?", (pid,)).fetchone()
        assert row[0] == 103.0
    finally:
        os.unlink(path)


# ── the overnight-drift exclusion on the real ledger ────────────────────────
def test_overnight_drift_excluded_live():
    L, path, pid = _ledger_with_pending()
    try:
        h = LiveActivationHandler(ledger=L, market=_Market(103.0),
                                  now_fn=lambda: OPEN + timedelta(minutes=1))
        h.activate_pending(Family.STOCKS, "RUN-1")
        L.resolve(pid, exit_price=108.0)
        row = sqlite3.connect(path).execute(
            "SELECT realised_ret FROM predictions WHERE id=?", (pid,)).fetchone()
        from_open = 108 / 103 - 1          # 4.85%
        from_scan = 108 / 100 - 1          # 8.00% (the bug)
        assert abs(row[0] - from_open) < 0.01
        assert abs(row[0] - from_scan) > 0.02
    finally:
        os.unlink(path)


# ── never before the execution point ────────────────────────────────────────
def test_no_activation_before_execution_point():
    L, path, pid = _ledger_with_pending()
    try:
        h = LiveActivationHandler(ledger=L, market=_Market(),
                                  now_fn=lambda: SCAN)   # before OPEN
        assert h.activate_pending(Family.STOCKS, "RUN-1") == 0
        row = sqlite3.connect(path).execute(
            "SELECT entry_price FROM predictions WHERE id=?", (pid,)).fetchone()
        assert row[0] is None
    finally:
        os.unlink(path)


# ── leaves pending if the open price isn't available yet ────────────────────
def test_leaves_pending_without_price():
    L, path, pid = _ledger_with_pending()
    try:
        h = LiveActivationHandler(ledger=L, market=_EmptyMarket(),
                                  now_fn=lambda: OPEN + timedelta(minutes=1))
        assert h.activate_pending(Family.STOCKS, "RUN-1") == 0
        row = sqlite3.connect(path).execute(
            "SELECT entry_price FROM predictions WHERE id=?", (pid,)).fetchone()
        assert row[0] is None             # never guesses a price
    finally:
        os.unlink(path)


# ── idempotent ──────────────────────────────────────────────────────────────
def test_activation_idempotent():
    L, path, pid = _ledger_with_pending()
    try:
        h = LiveActivationHandler(ledger=L, market=_Market(103.0),
                                  now_fn=lambda: OPEN + timedelta(minutes=1))
        assert h.activate_pending(Family.STOCKS, "RUN-1") == 1
        assert h.activate_pending(Family.STOCKS, "RUN-2") == 0   # already done
    finally:
        os.unlink(path)


# ── lineage ──────────────────────────────────────────────────────────────────
def test_lineage_recorded():
    L, path, pid = _ledger_with_pending()
    try:
        h = LiveActivationHandler(ledger=L, market=_Market(103.0),
                                  now_fn=lambda: OPEN + timedelta(minutes=1))
        h.activate_pending(Family.STOCKS, "RUN-0042")
        lin = h.lineage()
        assert len(lin) == 1
        assert lin[0]["run_id"] == "RUN-0042"
        assert lin[0]["prediction_id"] == pid
        assert lin[0]["activation_price"] == 103.0
    finally:
        os.unlink(path)


# ── only stocks, creates no predictions ─────────────────────────────────────
def test_non_stocks_family_noop():
    L, path, pid = _ledger_with_pending()
    try:
        h = LiveActivationHandler(ledger=L, market=_Market(),
                                  now_fn=lambda: OPEN + timedelta(minutes=1))
        assert h.activate_pending(Family.CRYPTO, "RUN-1") == 0
    finally:
        os.unlink(path)


def test_handler_creates_no_predictions():
    L, path, pid = _ledger_with_pending()
    try:
        before = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM predictions").fetchone()[0]
        h = LiveActivationHandler(ledger=L, market=_Market(103.0),
                                  now_fn=lambda: OPEN + timedelta(minutes=1))
        h.activate_pending(Family.STOCKS, "RUN-1")
        after = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM predictions").fetchone()[0]
        assert before == after            # activation adds no rows
    finally:
        os.unlink(path)
