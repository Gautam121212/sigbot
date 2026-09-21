"""The whole desk, end to end, on a crash-and-recovery path.

Every serious bug this project has had passed its own unit tests and failed
only when pieces met: sizing that never read real rows (B80), breakers never
seeded from the ledger (B83), stops never applied at resolution (B84). This
test runs a sequence of trades through the REAL code paths — record, resolve
with stops, replay, seed, decide — and checks the invariants that only hold
if the pieces agree.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

import sigbot.runner as runner
from sigbot import paper
from sigbot.risk import decide
from sigbot.shadow import ShadowLedger


class _S:
    def __init__(self, path):
        self.shadow_db = str(path)
        self.history_start = "2026-01-01"


def _market(paths):
    """symbol -> list of (low, high, close) for the days after entry."""
    class M:
        def history(self, symbol, *_a, **_k):
            rows = paths[symbol]
            idx = pd.to_datetime([f"2026-02-{d:02d}" for d in range(1, len(rows) + 1)])
            return pd.DataFrame({"low": [r[0] for r in rows],
                                 "high": [r[1] for r in rows],
                                 "close": [r[2] for r in rows]}, index=idx)
    return M()


def _enter(settings, symbol, stop, day):
    ledger = ShadowLedger(settings.shadow_db)
    pid = ledger.record("stocks", symbol, "BUY", 0.7, stop, 100.0)
    con = sqlite3.connect(settings.shadow_db)
    con.execute("UPDATE predictions SET created_at=?, resolve_after=? WHERE id=?",
                (f"2026-01-{day:02d}T00:00:00", f"2000-01-{day:02d}T00:00:00", pid))
    con.commit()
    return ledger


def test_a_crash_then_recovery_behaves_like_a_disciplined_desk(tmp_path):
    settings = _S(tmp_path / "s.db")
    # Four names crash straight through a 5% stop, then recover hard — the
    # classic trap where a fixed-clock exit would record a win.
    crash = [(97, 100, 98), (80, 90, 85), (85, 120, 118)]
    # One name never touches its stop and closes up.
    clean = [(99, 103, 102), (100, 106, 105), (103, 110, 108)]
    paths = {"A": crash, "B": crash, "C": crash, "D": crash, "E": clean}

    for day, sym in enumerate(["E", "A", "B", "C", "D"], start=1):
        ledger = _enter(settings, sym, stop=0.05, day=day)
    runner.run_resolve(_market(paths), settings)

    book = paper.replay(settings.shadow_db)
    by_symbol = {t.symbol: t for t in book.trades}

    # 1. Stops are honoured: every crash trade exits at its stop, not at the
    #    118 recovery a clock exit would have recorded.
    for sym in "ABCD":
        assert abs(by_symbol[sym].exit_price - 95.0) < 1e-6, sym

    # 2. No stopped loss exceeds about one R plus costs.
    one_r = 100_000 * 0.01
    for sym in "ABCD":
        assert by_symbol[sym].pnl > -1.1 * one_r, (sym, by_symbol[sym].pnl)

    # 3. The winner was allowed to run to the close.
    assert by_symbol["E"].exit_price == 108.0 and by_symbol["E"].pnl > 0

    # 4. Paper equity is exactly the sum of its trades.
    assert abs(book.equity - (book.starting_cash + sum(t.pnl for t in book.trades))) < 1e-6

    # 5. The four losses came last, so the streak is four and the desk stands
    #    aside on the next signal.
    state = runner._seed_risk_state(ledger, settings)
    assert state.loss_streak == 4
    assert state.equity < state.peak_equity
    from dataclasses import replace
    nxt = decide(replace(state, day_pnl_pct=0.0), entry_price=100.0, stop_price=94.0)
    assert not nxt.allowed and "in a row" in nxt.reason


def test_a_win_resets_the_desk_so_it_trades_again(tmp_path):
    settings = _S(tmp_path / "s.db")
    crash = [(97, 100, 98), (80, 90, 85), (85, 120, 118)]
    clean = [(99, 103, 102), (100, 106, 105), (103, 110, 108)]
    paths = {"A": crash, "B": crash, "C": crash, "D": crash, "E": clean}

    for day, sym in enumerate(["A", "B", "C", "D", "E"], start=1):
        ledger = _enter(settings, sym, stop=0.05, day=day)
    runner.run_resolve(_market(paths), settings)

    state = runner._seed_risk_state(ledger, settings)
    assert state.loss_streak == 0, "the most recent close was a win"
