"""A price that never moved is a non-observation, not a miss.

This was the most damaging bug in the system. 47% of the daily model's record
had exit_price identical to entry_price — the resolver reading back the same
quote it opened on, because no new bar existed yet. A zero move can never
clear the cost bar, so every one of those rows scored an automatic miss.

The damage was not the lost rows. It was that the measured CHANCE LEVEL is
derived from the same rows: the null fell from 45.0% to 23.6%, so every tier,
colour, gate and verdict in the system was computed against a number that
described a resolver bug rather than a market.
"""
from __future__ import annotations

import sqlite3

from sigbot.shadow import ShadowLedger


def test_a_frozen_price_does_not_resolve(tmp_path):
    path = str(tmp_path / "s.db")
    ledger = ShadowLedger(path)
    pid = ledger.record("news", "AAPL", "BUY", 0.8, 0.02, 100.0)

    ledger.resolve(pid, 100.0)
    con = sqlite3.connect(path)
    assert con.execute("SELECT hit FROM predictions WHERE id=?",
                       (pid,)).fetchone()[0] is None, (
        "an unchanged price is no new bar — it must stay unresolved")


def test_it_resolves_normally_once_a_real_bar_arrives(tmp_path):
    path = str(tmp_path / "s.db")
    ledger = ShadowLedger(path)
    pid = ledger.record("news", "AAPL", "BUY", 0.8, 0.02, 100.0)

    ledger.resolve(pid, 100.0)
    ledger.resolve(pid, 104.0)
    con = sqlite3.connect(path)
    assert con.execute("SELECT hit FROM predictions WHERE id=?",
                       (pid,)).fetchone()[0] == 1


def test_frozen_rows_do_not_drag_the_measured_null(tmp_path):
    """The null is computed from the same rows, so frozen ones halved it."""
    path = str(tmp_path / "s.db")
    ledger = ShadowLedger(path)

    for i in range(20):
        pid = ledger.record("news", f"S{i}", "BUY", 0.8, 0.02, 100.0)
        ledger.resolve(pid, 104.0 if i % 2 else 96.0)
    clean = ledger.empirical_null("news")

    for i in range(20):
        pid = ledger.record("news", f"F{i}", "BUY", 0.8, 0.02, 100.0)
        ledger.resolve(pid, 100.0)          # refused, so no effect
    assert ledger.empirical_null("news") == clean, (
        "frozen rows must not enter the chance calculation")


def test_the_reset_unscores_frozen_rows_rather_than_deleting(tmp_path):
    """The forecast was real. Only the scoring was wrong, so the row is
    returned to unresolved and can be scored properly later."""
    import sigbot.runner as runner

    path = str(tmp_path / "s.db")
    ledger = ShadowLedger(path)
    pid = ledger.record("daily", "AAPL", "BUY", 0.8, 0.02, 100.0)
    con = sqlite3.connect(path)
    con.execute("UPDATE predictions SET exit_price=100.0, hit=0, "
                "outcome_mode='magnitude_short' WHERE id=?", (pid,))
    con.commit()

    runner.run_reset(settings=type("S", (), {"shadow_db": path})())

    row = sqlite3.connect(path).execute(
        "SELECT hit, entry_price FROM predictions WHERE id=?", (pid,)).fetchone()
    assert row is not None, "the forecast must survive"
    assert row[0] is None, "but it must no longer be scored"
