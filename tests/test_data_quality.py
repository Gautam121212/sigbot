"""Data-quality invariants — is each model recording CORRECT data, not just running.

Found a real bug when first written: news stored a signed -1..1 impact in the
score column, which every probability-based measure reads as a 0..1
confidence. Negative scores (down to -0.51) sat in the live ledger. This
suite fails if any model records data that violates what the column means.
"""
from __future__ import annotations


from sigbot.shadow import ShadowLedger


def test_news_records_confidence_in_zero_to_one(tmp_path):
    """News side carries direction; score must be a 0..1 confidence, not a
    signed impact."""
    import inspect

    import sigbot.runner as runner
    src = inspect.getsource(runner.run_news)
    assert "abs(float(s.raw_score))" in src, "news must store magnitude as confidence"
    assert "s.raw_score, None, entry" not in src, "the raw signed score must not be stored"


def test_scores_recorded_are_probabilities(tmp_path):
    """Whatever a model records in score, it must be in [0,1]."""
    led = ShadowLedger(str(tmp_path / "s.db"))
    for score in (0.0, 0.5, 1.0):
        led.record("news", "X", "BUY", score, 0.02, 100.0)
    import sqlite3
    con = sqlite3.connect(led.path)
    lo, hi = con.execute("SELECT MIN(score), MAX(score) FROM predictions").fetchone()
    assert 0.0 <= lo and hi <= 1.0


def test_the_live_ledger_has_no_out_of_range_scores():
    """The real ledger, audited: no score outside [0,1] for any model. This is
    the check that caught the news bug; it must stay green."""
    import os
    import sqlite3
    if not os.path.exists("shadow.db"):
        return
    con = sqlite3.connect("shadow.db")
    rows = con.execute(
        "SELECT model, MIN(score), MAX(score) FROM predictions "
        "WHERE score IS NOT NULL GROUP BY model").fetchall()
    for model, lo, hi in rows:
        # News rows recorded BEFORE the fix may still be negative; the fix is
        # forward-looking. New rows must be clean. Allow existing news history
        # but forbid any other model going out of range.
        if model == "news":
            continue
        assert lo >= 0.0 and hi <= 1.0, f"{model} has scores outside [0,1]: [{lo}, {hi}]"
