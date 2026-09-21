"""Resolution must honour the stop, or the exit plan is decoration.

Resolution scored every trade at the latest close and never looked at what
happened on the way, so the live system behaved as a fixed clock whatever the
exit plan said. On history the ATR stop was worth +0.759% -> +1.424% a trade,
the largest single improvement measured — and none of it reached live scoring.
"""
from __future__ import annotations

import pandas as pd

import sigbot.runner as runner
from sigbot.shadow import ShadowLedger


class _S:
    def __init__(self, path):
        self.shadow_db = str(path)
        self.history_start = "2026-01-01"


class _Market:
    def __init__(self, lows, closes):
        idx = pd.to_datetime([f"2026-01-{d:02d}" for d in range(2, 2 + len(closes))])
        self.bars = pd.DataFrame({"low": lows, "high": [c + 1 for c in closes],
                                  "close": closes}, index=idx)

    def history(self, *_a, **_k):
        return self.bars


def _due_trade(settings, model, stop):
    import sqlite3
    ledger = ShadowLedger(settings.shadow_db)
    pid = ledger.record(model, "AAPL", "BUY", 0.7, stop, 100.0)
    con = sqlite3.connect(settings.shadow_db)
    con.execute("UPDATE predictions SET created_at='2026-01-01T00:00:00', "
                "resolve_after='2000-01-01T00:00:00' WHERE id=?", (pid,))
    con.commit()
    return ledger, pid


def _exit(settings, pid):
    import sqlite3
    return sqlite3.connect(settings.shadow_db).execute(
        "SELECT exit_price FROM predictions WHERE id=?", (pid,)).fetchone()[0]


def test_a_stocks_trade_that_hit_its_stop_resolves_at_the_stop(tmp_path):
    settings = _S(tmp_path / "s.db")
    _ledger, pid = _due_trade(settings, "stocks", stop=0.05)
    # Dipped to 90 (through the 95 stop), then recovered to close at 104.
    runner.run_resolve(_Market(lows=[98, 90, 99], closes=[99, 96, 104]), settings)
    assert abs(_exit(settings, pid) - 95.0) < 1e-6, (
        "a trade that went through its stop must be scored at the stop, not "
        "at a later recovery the account would never have seen")


def test_a_stocks_trade_that_never_touched_its_stop_resolves_at_the_close(tmp_path):
    settings = _S(tmp_path / "s.db")
    _ledger, pid = _due_trade(settings, "stocks", stop=0.05)
    runner.run_resolve(_Market(lows=[98, 97, 99], closes=[99, 101, 104]), settings)
    assert abs(_exit(settings, pid) - 104.0) < 1e-6


def test_other_models_are_unaffected(tmp_path):
    """Only stocks records a stop distance. Every other model's
    `expected_move` is a forecast, and reading it as a stop is B80 again."""
    settings = _S(tmp_path / "s.db")
    _ledger, pid = _due_trade(settings, "daily", stop=0.05)
    runner.run_resolve(_Market(lows=[98, 90, 99], closes=[99, 96, 104]), settings)
    assert abs(_exit(settings, pid) - 104.0) < 1e-6
