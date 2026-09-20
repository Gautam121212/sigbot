"""Tests for history depth.

A shallow asset is not rejected, it is early. These check the system says which
one it means.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sigbot.history import (
    MIN_COVERAGE, PRECEDENT_MIN_YEARS, Depth, growth_report, measure,
    precedent_universe, rank,
)


def _bars(years: float, seed: int = 1, gaps: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Build the index first and take its length. Asking bdate_range for N bars
    # ending on a Sunday returns N-1, which is how this helper first broke.
    idx = pd.bdate_range(end="2026-08-28", periods=int(years * 252))
    n = len(idx)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame(dict(open=close, high=close * 1.01, low=close * 0.99,
                           close=close, volume=rng.lognormal(12, 0.3, n)), index=idx)
    if gaps:                      # drop a contiguous block to simulate a halt
        keep = np.ones(n, bool)
        keep[n // 2: n // 2 + gaps] = False
        df = df[keep]
    return df


@pytest.mark.parametrize("years,expected", [
    (15, Depth.DEEP), (11, Depth.DEEP),
    (7, Depth.MEDIUM), (5.5, Depth.MEDIUM),
    (3, Depth.SHALLOW), (2.2, Depth.SHALLOW),
    (1, Depth.NEW), (0.4, Depth.NEW),
])
def test_depth_follows_usable_history(years, expected):
    assert measure(_bars(years), "X").depth is expected


def test_only_deep_and_medium_do_precedent_work():
    assert measure(_bars(12), "OLD").precedent_eligible
    assert measure(_bars(6), "MID").precedent_eligible
    assert not measure(_bars(3), "YOUNG").precedent_eligible
    assert not measure(_bars(1), "NEW").precedent_eligible


def test_a_gappy_frame_is_reported_as_the_shorter_thing_it_is():
    """Span is not history. A frame that is mostly holes must not pass as deep."""
    full = _bars(12)
    holed = full.iloc[::3]                       # keep a third of the bars
    m = measure(holed, "GAPPY")
    assert m.span_years > 11, "the span is unchanged"
    assert m.usable_years < 5, "but the record is not"
    assert m.coverage < MIN_COVERAGE
    assert not m.precedent_eligible
    assert "missing" in m.gap_note


def test_a_long_halt_is_noted_without_disqualifying():
    m = measure(_bars(12, gaps=40), "HALTED")
    assert m.precedent_eligible
    assert "gap" in m.gap_note or m.gap_note == ""


def test_empty_and_broken_frames_are_new_not_crashes():
    for bad in (None, pd.DataFrame(), pd.DataFrame({"x": [1, 2]})):
        m = measure(bad, "BAD")
        assert m.depth is Depth.NEW and not m.precedent_eligible


# ------------------------------------------------- the growth question

def test_a_shallow_asset_gets_a_date_not_a_rejection():
    """'Qualifies in 14 months' is a plan. Silence is a decision nobody made."""
    m = measure(_bars(3), "RIVN")
    months = m.qualifies_in_months()
    assert months is not None and 20 < months < 30
    when = m.eligible_on()
    assert when is not None and when.isoformat() > m.last_bar
    assert "Qualifies around" in m.render()


def test_an_eligible_asset_has_no_countdown():
    m = measure(_bars(12), "OLD")
    assert m.qualifies_in_months() is None and m.eligible_on() is None
    assert "Eligible for precedent" in m.render()


def test_the_countdown_shrinks_as_history_accrues():
    a = measure(_bars(2), "A").qualifies_in_months()
    b = measure(_bars(4), "B").qualifies_in_months()
    assert a is not None and b is not None and b < a


def test_precedent_minimum_matches_the_medium_threshold():
    assert PRECEDENT_MIN_YEARS == 5.0
    assert measure(_bars(PRECEDENT_MIN_YEARS + 0.2), "X").precedent_eligible
    assert not measure(_bars(PRECEDENT_MIN_YEARS - 0.5), "X").precedent_eligible


# ------------------------------------------------------------- routing

def test_ranking_puts_the_deepest_first():
    frames = {"NEW": _bars(1), "OLD": _bars(15), "MID": _bars(6)}
    assert [h.symbol for h in rank(frames)] == ["OLD", "MID", "NEW"]


def test_the_precedent_universe_excludes_the_shallow():
    frames = {"OLD": _bars(15), "MID": _bars(6), "YOUNG": _bars(2)}
    assert set(precedent_universe(frames)) == {"OLD", "MID"}
    assert precedent_universe(frames, limit=1) == ["OLD"]


def test_growth_report_names_both_now_and_later():
    frames = {"OLD": _bars(15), "MID": _bars(6), "YOUNG": _bars(3), "NEW": _bars(1)}
    text = growth_report(frames)
    assert "2 of 4 assets" in text
    assert "Eligible now" in text and "OLD" in text
    assert "Becomes eligible" in text and "YOUNG" in text
    assert "months" in text
    assert "still noise" in text, "depth must not be sold as quality"


def test_growth_report_survives_an_all_new_universe():
    text = growth_report({"A": _bars(1), "B": _bars(0.5)})
    assert "0 of 2" in text and "Becomes eligible" in text
