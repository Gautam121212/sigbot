"""Fractional-Kelly sizing: the profitable gate that admits risk safely."""
from __future__ import annotations

from sigbot.sizing import (
    KELLY_FRACTION, MAX_RISK_FRACTION, kelly_fraction, size, size_from_record,
)


def test_a_positive_edge_gets_a_small_capped_stake_not_a_rejection():
    """The whole point: risky-but-positive is SIZED, not blocked."""
    s = size(0.55, 2.0)
    assert s.take and 0 < s.risk_fraction <= MAX_RISK_FRACTION


def test_a_negative_edge_gets_zero():
    s = size(0.40, 1.0)
    assert not s.take and s.risk_fraction == 0.0
    assert "negative edge" in s.reason


def test_the_cap_is_never_exceeded_however_strong_the_edge():
    """A huge edge still cannot risk ruin."""
    s = size(0.90, 5.0)
    assert s.risk_fraction == MAX_RISK_FRACTION
    assert "capped" in s.reason


def test_only_a_fraction_of_full_kelly_is_ever_risked():
    """Full Kelly is too volatile; professionals take a quarter to a half."""
    full = kelly_fraction(0.55, 2.0)
    s = size(0.55, 2.0, cap=1.0)         # lift the cap to see the fraction
    assert abs(s.risk_fraction - full * KELLY_FRACTION) < 1e-3  # code rounds to 4dp


def test_a_thin_edge_is_skipped_as_not_worth_the_slot():
    s = size(0.48, 1.1)
    assert not s.take and "thin" in s.reason


def test_sizing_from_a_live_record():
    strong = size_from_record(35, 20, 0.06, 0.04)
    assert strong.take
    weak = size_from_record(20, 35, 0.04, 0.06)   # losing record
    assert not weak.take
    thin = size_from_record(5, 3, 0.06, 0.04)     # too few trades
    assert not thin.take and "too few" in thin.reason


def test_negative_kelly_means_stop_not_shrink():
    """A negative edge returns zero — the fix for a bad edge is to stop, never
    to size it down and keep going."""
    assert kelly_fraction(0.30, 1.0) < 0
    assert size(0.30, 1.0).risk_fraction == 0.0
