"""Tests for the tiering and failure-classification layer.

`test_tier_cannot_be_reached_by_lowering_the_bar` is the important one. It
encodes the reason the calendar-phase design was rejected: a gate that moves to
accommodate the evidence is not a gate, and no code path may lower one.
"""
from __future__ import annotations

import pytest

from sigbot.shadow import ShadowLedger
from sigbot.stats import wilson_interval
from sigbot.tiers import (
    TIER_RULES,
    Failure,
    Tier,
    classify_outcome,
    classify_tier,
    observations_needed,
    render_track_record,
)


# ------------------------------------------------------------------- tiers

def test_no_tier_without_evidence():
    assert classify_tier(0, 0)[0] is Tier.SILENT
    assert classify_tier(8, 6)[0] is Tier.SILENT, "8 observations proves nothing"
    assert classify_tier(20, 14)[0] is Tier.SILENT, "20 at 70% still misses WATCH"


def test_tiers_are_monotone_in_evidence():
    """More observations at the same rate can only move you up, never down."""
    seen = []
    for n in (25, 60, 150, 400, 1000):
        tier, lower = classify_tier(n, round(0.68 * n))
        seen.append((n, tier, lower))
    order = [t.value for _, t, _ in seen]
    ranks = {Tier.SILENT: 0, Tier.WATCH: 1, Tier.CAUTION: 2, Tier.TRADE: 3}
    ranked = [ranks[Tier(o)] for o in order]
    assert ranked == sorted(ranked), f"tier went backwards with more data: {seen}"


def test_tier_cannot_be_reached_by_lowering_the_bar():
    """The rejected design's own example: 40 observations aiming at a 60% gate.

    Even at an observed 70% hit rate the lower bound is 57.1%. The only way to
    call that a TRADE signal is to move the gate down to meet it.
    """
    lower, _ = wilson_interval(round(0.70 * 40), 40, 0.90)
    assert lower == pytest.approx(0.571, abs=0.005)
    assert classify_tier(40, 28)[0] is not Tier.TRADE

    trade_rule = next(r for r in TIER_RULES if r.tier is Tier.TRADE)
    assert trade_rule.min_lower_bound == 0.60
    assert trade_rule.min_observations >= 58, (
        "TRADE floor must be at least the n where a 70% rate clears 60%"
    )


def test_observations_needed_is_honest_about_the_unreachable():
    # At a 70% observed rate the lower bound clears 60% by n=58, but TRADE also
    # carries a 150-observation floor, so the floor is what binds. Reporting the
    # looser of the two constraints would understate what is actually required.
    assert observations_needed(Tier.TRADE, 0.70) == 150
    assert wilson_interval(round(0.70 * 58), 58, 0.90)[0] >= 0.60
    assert observations_needed(Tier.TRADE, 0.52) is None, (
        "a 52% hit rate never clears a 60% floor, and must not pretend otherwise"
    )


def test_render_states_the_gap_rather_than_a_schedule():
    text = render_track_record("NVDA", "news", 30, 21)
    assert "TRADE tier needs" in text
    assert "Day" not in text and "days" not in text, "tier must not be time-framed"


# ---------------------------------------------------------------- failures

ENTRY = 100.0


def test_win_is_net_of_costs():
    mode, net = classify_outcome("BUY", ENTRY, 100.0, 104.0, 99.5, 103.0, cost_pct=0.0015)
    assert mode is Failure.WIN and net > 0


def test_right_direction_but_inside_costs():
    mode, net = classify_outcome("BUY", ENTRY, 100.0, 100.1, 99.9, 100.05, cost_pct=0.0015)
    assert mode is Failure.MAGNITUDE_SHORT and net < 0


def test_reversal_is_distinguished_from_plain_wrong():
    rev, _ = classify_outcome("BUY", ENTRY, 100.0, 101.5, 98.0, 98.5)
    wrong, _ = classify_outcome("BUY", ENTRY, 100.0, 100.1, 98.0, 98.5)
    assert rev is Failure.REVERSAL
    assert wrong is Failure.DIRECTION_WRONG


def test_gap_against_takes_priority():
    mode, _ = classify_outcome("BUY", ENTRY, 97.0, 99.0, 96.0, 97.5)
    assert mode is Failure.GAP_AGAINST


def test_short_side_is_mirrored():
    mode, net = classify_outcome("SELL", ENTRY, 100.0, 100.5, 96.0, 97.0)
    assert mode is Failure.WIN and net > 0
    mode2, _ = classify_outcome("SELL", ENTRY, 100.0, 104.0, 99.9, 103.0)
    assert mode2 is Failure.DIRECTION_WRONG


def test_missing_bar_data_degrades_without_inventing():
    mode, _ = classify_outcome("BUY", ENTRY, None, None, None, 98.0)
    assert mode is Failure.DIRECTION_WRONG


def test_no_unlearnable_failure_categories_exist():
    """Categories that cannot be derived from price data must not be offered."""
    names = {f.value for f in Failure}
    for banned in ("news_conflict", "low_liquidity", "random"):
        assert banned not in names


# ------------------------------------------------------------------ ledger

def test_ledger_records_and_aggregates_failure_modes(tmp_path):
    led = ShadowLedger(tmp_path / "t.db")
    a = led.record("news", "NVDA", "BUY", 0.6, 0.02, ENTRY, horizon_hours=-1)
    b = led.record("news", "NVDA", "BUY", 0.6, 0.02, ENTRY, horizon_hours=-1)
    led.resolve(a, 103.0, bar_open=100.0, bar_high=104.0, bar_low=99.5)
    led.resolve(b, 98.5, bar_open=100.0, bar_high=101.5, bar_low=98.0)

    modes = led.failure_modes("news", "NVDA")
    assert modes.get(Failure.WIN.value) == 1
    assert modes.get(Failure.REVERSAL.value) == 1

    tier, lower, n = led.tier("news", "NVDA")
    assert (tier, n) == (Tier.SILENT, 2) and lower < 0.5


def test_ledger_migrates_a_pre_tier_database(tmp_path):
    """An existing ledger must not be orphaned by the schema change."""
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "model TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, score REAL, "
            "expected_move REAL, created_at TEXT NOT NULL, resolve_after TEXT NOT NULL, "
            "entry_price REAL, exit_price REAL, realised_ret REAL, hit INTEGER, payload TEXT)"
        )
    led = ShadowLedger(path)
    pid = led.record("daily", "AAPL", "BUY", 0.6, 0.01, ENTRY, horizon_hours=-1)
    led.resolve(pid, 102.0, bar_open=100.0, bar_high=102.5, bar_low=99.8)
    assert led.failure_modes("daily").get(Failure.WIN.value) == 1
