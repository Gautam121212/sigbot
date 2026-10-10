"""Prediction transparency — every prediction visible and verifiable."""
from sigbot.prediction_transparency import (
    HORIZON_DAYS, summary, todays_predictions)


def test_horizons_match_the_real_edges():
    # ventures/opportunity are quarterly; crypto is fast; stocks 20d
    assert HORIZON_DAYS["ventures"] == 90
    assert HORIZON_DAYS["crypto"] == 3
    assert HORIZON_DAYS["stocks"] == 20


def test_missing_ledger_is_honest_not_fabricated(tmp_path):
    """No ledger -> honest empty state, never made-up predictions."""
    missing = str(tmp_path / "nonexistent.db")   # tmp_path: never pollute the project root
    assert todays_predictions(missing) == []
    out = summary(missing)
    assert "No predictions" in out and "real predictions" in out


def test_summary_never_invents_numbers(tmp_path):
    out = summary(str(tmp_path / "nonexistent.db"))   # tmp_path: never pollute the project root
    # it must not claim any hit rate or count when there's no data
    assert "%" not in out or "verify" in out
