"""Tests for the skip ledger.

A silent skip is worse than a crash: a crash tells you to look, a silent skip
hands you a smaller answer that looks exactly as confident as a complete one.
These tests exist to keep that failure from coming back.
"""
from __future__ import annotations

import pytest

from sigbot.skips import (
    InsufficientCoverage, record_skip, report, require_coverage, reset,
    skipped_count, tracking,
)


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


def test_a_clean_run_says_nothing():
    rep = report("screen", 100)
    assert rep.skipped == 0 and rep.coverage == 1.0
    assert rep.line() == "", "no news should be no message"
    assert "all 100 completed" in rep.detail()


def test_skips_are_counted_and_named():
    for i in range(40):
        record_skip("screen", f"S{i}", ValueError("no data"))
    for i in range(6):
        record_skip("screen", f"X{i}", KeyError("close"))

    rep = report("screen", 156)
    assert rep.skipped == 46 and rep.completed == 110
    assert rep.coverage == pytest.approx(110 / 156)
    line = rep.line()
    assert "46 of 156" in line and "ValueError 40" in line and "71%" in line


def test_examples_are_capped_but_the_count_is_not():
    for i in range(50):
        record_skip("screen", f"S{i}", ValueError("boom"))
    rep = report("screen", 60)
    assert rep.skipped == 50
    assert len(rep.examples) <= 8, "detail must not become the whole failure list"
    assert "and 42 more" in rep.detail()


def test_operations_do_not_leak_into_each_other():
    record_skip("screen", "A", ValueError("x"))
    record_skip("charts", "B", KeyError("y"))
    assert skipped_count("screen") == 1
    assert skipped_count("charts") == 1
    assert report("screen", 10).reasons["KeyError"] == 0


def test_counts_are_scoped_per_run():
    """A count from this morning must not make tonight's run look broken."""
    with tracking("publish"):
        record_skip("publish", "A", ValueError("x"))
        assert skipped_count("publish") == 1
    with tracking("publish"):
        assert skipped_count("publish") == 0


def test_reset_of_one_operation_leaves_the_others():
    record_skip("screen", "A", ValueError("x"))
    record_skip("charts", "B", ValueError("y"))
    reset("screen")
    assert skipped_count("screen") == 0 and skipped_count("charts") == 1


# ------------------------------------------------------------ fail closed

def test_thin_coverage_raises_rather_than_returning_a_partial_answer():
    for i in range(70):
        record_skip("contagion", f"S{i}", ValueError("no data"))
    with pytest.raises(InsufficientCoverage, match="below the"):
        require_coverage("contagion", 100, minimum=0.60)


def test_adequate_coverage_passes_and_still_reports():
    for i in range(20):
        record_skip("contagion", f"S{i}", ValueError("x"))
    rep = require_coverage("contagion", 100, minimum=0.60)
    assert rep.coverage == 0.8
    assert "20 of 100" in rep.line(), "passing the gate is not a reason to go quiet"


def test_nothing_attempted_is_not_a_failure():
    assert require_coverage("empty", 0).coverage == 1.0


# -------------------------------------------------- wired into the pipeline

def test_the_screen_reports_what_it_could_not_load():
    import pandas as pd

    from sigbot.providers.market import SyntheticProvider
    from sigbot.screener import explain, screen

    good = SyntheticProvider(seed=2).history("G", "2022-01-01", "2026-01-01")
    bars = {f"G{i}": good for i in range(3)}
    bars["BROKEN"] = pd.DataFrame({"close": ["x"] * 500, "volume": [1] * 500,
                                   "open": [1] * 500, "high": [1] * 500,
                                   "low": [1] * 500})
    reset()
    results = screen(bars, {k: "equity" for k in bars})
    text = explain(results, target=3)
    assert skipped_count("screen") >= 1, "a broken frame was skipped in silence"
    assert "could not be processed" in text
    assert "%" in text


def test_a_broken_board_says_so_instead_of_looking_empty(tmp_path):
    from sigbot.export_app import build_export

    d = build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                     watchlist_path="/nonexistent/dir/w.db")
    board = d["board"]
    assert board["size"] == 0
    assert "could not be built" in board.get("note", ""), (
        "an empty board and a broken board look identical and mean opposite things")


def test_the_same_item_failing_twice_counts_once():
    """A symbol that fails computing returns and again when scored is one
    skipped asset. Counting it twice reported 16 of 28 for eight broken symbols
    out of twenty — a wrong number, stated confidently."""
    exc = ValueError("no data")
    for _ in range(3):
        record_skip("screen", "NVDA", exc)
    record_skip("screen", "AAPL", exc)
    assert skipped_count("screen") == 2


def test_dedup_is_per_operation():
    record_skip("screen", "NVDA", ValueError("x"))
    record_skip("charts", "NVDA", ValueError("x"))
    assert skipped_count("screen") == 1 and skipped_count("charts") == 1


def test_dedup_resets_between_runs():
    with tracking("screen"):
        record_skip("screen", "NVDA", ValueError("x"))
    with tracking("screen"):
        record_skip("screen", "NVDA", ValueError("x"))
        assert skipped_count("screen") == 1, "a new run must count it again"


def test_explain_uses_the_real_candidate_count():
    import pandas as pd

    from sigbot.providers.market import SyntheticProvider
    from sigbot.screener import explain, screen

    good = SyntheticProvider(seed=2).history("G", "2022-01-01", "2026-01-01")
    bars = {f"OK{i}": good for i in range(12)}
    broken = pd.DataFrame({"close": ["x"] * 500, "volume": [1] * 500,
                           "open": [1] * 500, "high": [1] * 500, "low": [1] * 500})
    for i in range(8):
        bars[f"BAD{i}"] = broken

    reset()
    text = explain(screen(bars, {k: "equity" for k in bars}), 10, attempted=len(bars))
    assert "8 of 20" in text, "the denominator must be what was actually attempted"
    assert "60%" in text
