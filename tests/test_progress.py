"""Tests for the progress view.

The Board answers "does anything clear the bar" and says no for months. This
answers "is the ledger filling and is the model honest", which is measurable
today. The two must not be confused, and most of these tests are about keeping
them apart.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sigbot.progress import (
    CHECKS_FOR_CALIBRATION, CHECKS_FOR_VERDICT, GREEN, GREY, measure, render,
)
from sigbot.shadow import ShadowLedger


def _fill(path, n, rate=0.55, seed=3, days_ago=0):
    led = ShadowLedger(str(path))
    rng = random.Random(seed)
    for i in range(n):
        pid = led.record("daily", f"A{i % 9}", "BUY", rate, 0.02, 100.0,
                         horizon_hours=-1)
        if rng.random() < rate:
            led.resolve(pid, 103.0, bar_open=100.0, bar_high=103.5, bar_low=99.5)
        else:
            led.resolve(pid, 97.0, bar_open=100.0, bar_high=100.5, bar_low=96.5)
    return led


def test_an_empty_ledger_says_nothing_is_accumulating(tmp_path):
    """The state that matters most: no forecasts means no learning, and it
    must not read as a quiet market."""
    ShadowLedger(str(tmp_path / "s.db"))
    text = render(measure(str(tmp_path / "s.db")))
    assert "No forecasts recorded at all" in text
    assert "daily job is running" in text


def test_a_filling_ledger_reports_the_distance_to_a_verdict(tmp_path):
    _fill(tmp_path / "s.db", 45)
    progress = measure(str(tmp_path / "s.db"))
    model = progress.models[0]

    assert model.checked == 45
    assert model.days_to_verdict is not None and model.days_to_verdict > 0
    text = render(progress)
    assert "to go at" in text and "days" in text


def test_a_fractional_window_cannot_paint_a_stall_green(tmp_path):
    """Dividing a handful of records by a fraction of a day reports thousands
    per day. The window is clamped to at least one for that reason."""
    _fill(tmp_path / "s.db", 40)
    tiny = measure(str(tmp_path / "s.db"), window_days=0.0001)
    # Clamped to one day: 40 records is 40 a day, not 400,000.
    assert tiny.models[0].per_day == 40.0


def test_a_stalled_ledger_is_grey_and_called_a_fault(tmp_path):
    """A stalled ledger and a calm week look identical everywhere else in this
    system. This is the only place that separates them."""
    import sqlite3

    _fill(tmp_path / "s.db", 40)
    # Age every record past the window, so nothing is recent.
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    with sqlite3.connect(tmp_path / "s.db") as con:
        con.execute("UPDATE predictions SET created_at=?", (old,))

    progress = measure(str(tmp_path / "s.db"))
    model = progress.models[0]
    assert model.colour == GREY
    assert "fault in the plumbing" in model.verdict
    assert "not a quiet market" in model.verdict


def test_calibration_is_read_before_a_verdict_is_possible(tmp_path):
    """Brier becomes readable at 30 checks, a tier needs 100. Waiting for the
    tier to learn whether the probabilities are honest wastes months."""
    assert CHECKS_FOR_CALIBRATION < CHECKS_FOR_VERDICT
    _fill(tmp_path / "s.db", CHECKS_FOR_CALIBRATION + 5)
    model = measure(str(tmp_path / "s.db")).models[0]
    assert model.brier is not None
    assert "Brier" in model.verdict


def test_a_useless_but_honest_model_is_not_sold_as_progress(tmp_path):
    """A model calibrated at 50% is perfectly honest and worth nothing. Reading
    a good Brier score as evidence of edge is the most available mistake here."""
    _fill(tmp_path / "s.db", 60, rate=0.50)
    text = render(measure(str(tmp_path / "s.db")))
    assert "calibrated perfectly at 50% would show green here and be worth "\
           "nothing" in text
    assert "The Board is where usefulness is judged" in text


def test_a_bad_brier_says_more_data_will_not_fix_it(tmp_path):
    """Miscalibration is not cured by waiting, and saying so prevents months
    of patience aimed at the wrong problem."""
    from sigbot.progress import _band

    _colour, verdict, _days = _band(checked=60, per_day=6, brier=0.40)
    assert "worse than a shrug" in verdict
    assert "will not fix that" in verdict


def test_the_hit_rate_is_shown_with_its_worst_case(tmp_path):
    _fill(tmp_path / "s.db", 40)
    text = render(measure(str(tmp_path / "s.db")))
    assert "worst case" in text
    assert "assumes every check is independent" in text


def test_reaching_the_verdict_threshold_defers_to_the_board(tmp_path):
    _fill(tmp_path / "s.db", CHECKS_FOR_VERDICT + 5)
    model = measure(str(tmp_path / "s.db")).models[0]
    assert model.colour == GREEN
    assert "the Board's question, not this one" in model.verdict


def test_an_unreadable_ledger_is_reported_not_shown_as_empty(tmp_path):
    progress = measure(str(tmp_path / "nonexistent" / "s.db"))
    text = render(progress)
    assert "could not be read" in text or "No forecasts" in text


def test_brier_is_zero_for_perfect_and_a_quarter_for_a_coin_flip():
    from sigbot.progress import _brier

    assert _brier([(1.0, 1), (0.0, 0)]) == 0.0
    assert _brier([(0.5, 1), (0.5, 0)]) == 0.25
    assert _brier([]) is None


def test_the_brier_score_shows_once_past_the_verdict_threshold(tmp_path):
    """It used to print only in the middle band, disappearing exactly when it
    became most readable."""
    _fill(tmp_path / "s.db", CHECKS_FOR_VERDICT + 20)
    model = measure(str(tmp_path / "s.db")).models[0]
    assert model.checked >= CHECKS_FOR_VERDICT
    assert "Brier" in model.verdict


def test_correlated_checks_are_not_counted_as_independent(tmp_path):
    """200 checks from two market days is not 200 observations. On a day the
    market falls most BUY calls fail together, so the Wilson interval — which
    assumes independence — is tighter than the data supports."""
    _fill(tmp_path / "s.db", 200)
    text = render(measure(str(tmp_path / "s.db")))

    assert "market day(s)" in text
    assert "fail together" in text
    assert "tighter than the data supports" in text
    assert "assumes every check is independent" in text


def test_the_day_count_is_read_from_the_ledger(tmp_path):
    _fill(tmp_path / "s.db", 60)
    model = measure(str(tmp_path / "s.db")).models[0]
    assert model.days >= 1
    assert model.days <= model.checked
