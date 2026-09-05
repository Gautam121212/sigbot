"""Tests for the adaptation layer.

The system could already say why it was wrong and then make the identical
assumption the next day. These tests cover the part that closes that, and the
guards that stop it chasing noise instead.
"""
from __future__ import annotations

import pytest

from sigbot.adapt import (
    COOLDOWN_DAYS, DEFAULT_HOURS, MAX_HOURS, MIN_HOURS, MIN_MISSES, MIN_SHARE,
    RESPONSES, Adaptations,
)
from sigbot.shadow import ShadowLedger


def _misses(led: ShadowLedger, symbol: str, mode: str, n: int, model: str = "daily"):
    """Write n resolved misses of a chosen kind, using real OHLC shapes."""
    shapes = {
        "direction_wrong": (97.0, 100.0, 100.2, 97.0),
        "magnitude_short": (100.05, 100.0, 100.1, 99.9),
        "reversal": (98.5, 100.0, 101.5, 98.0),
        "gap_against": (97.5, 97.0, 99.0, 96.0),
    }
    close, op, hi, lo = shapes[mode]
    for _ in range(n):
        pid = led.record(model, symbol, "BUY", 0.6, 0.02, 100.0, horizon_hours=-1)
        led.resolve(pid, close, bar_open=op, bar_high=hi, bar_low=lo)


@pytest.fixture
def setup(tmp_path):
    return ShadowLedger(tmp_path / "s.db"), Adaptations(tmp_path / "a.db")


# ------------------------------------------------------------ the guards

def test_nothing_happens_below_the_minimum(setup):
    led, ad = setup
    _misses(led, "NVDA", "direction_wrong", MIN_MISSES - 5)
    assert ad.diagnose(led) == [], "acted on too few misses"


def test_a_scatter_of_causes_changes_nothing(setup):
    """No single cause means no diagnosis, however many misses there are."""
    led, ad = setup
    for mode in ("direction_wrong", "magnitude_short", "reversal", "gap_against"):
        _misses(led, "NVDA", mode, 15)
    assert ad.diagnose(led) == []


def test_one_change_per_asset_per_cooldown(setup):
    led, ad = setup
    _misses(led, "NVDA", "magnitude_short", 60)
    first = ad.apply(ad.diagnose(led))
    assert len(first) == 1
    assert ad.diagnose(led) == [], f"changed again inside {COOLDOWN_DAYS} days"


def test_horizon_never_leaves_its_bounds(setup):
    led, ad = setup
    _misses(led, "NVDA", "magnitude_short", 60)
    for _ in range(20):
        d = ad.diagnose(led)
        if not d:
            break
        ad.apply(d)
    assert MIN_HOURS <= ad.hours_for("daily", "NVDA") <= MAX_HOURS


# --------------------------------------------------------- the diagnoses

def test_right_but_too_small_holds_longer(setup):
    led, ad = setup
    _misses(led, "AVGO", "magnitude_short", 60)
    d = ad.diagnose(led)[0]
    assert d.cause == "magnitude_short"
    assert d.new_hours > d.old_hours
    assert "clear costs" in d.reason
    assert "room to clear costs" in d.render()


def test_reversal_exits_sooner(setup):
    led, ad = setup
    _misses(led, "MU", "reversal", 60)
    d = ad.diagnose(led)[0]
    assert d.cause == "reversal" and d.new_hours < d.old_hours
    assert "sooner" in d.reason


def test_gapping_is_marked_untradeable_not_retuned(setup):
    """A horizon change cannot help with something that moves before you can act."""
    led, ad = setup
    _misses(led, "SPY", "gap_against", 60)
    d = ad.diagnose(led)[0]
    assert d.untradeable and not d.retire
    assert d.new_hours == d.old_hours
    ad.apply([d])
    assert ad.is_untradeable("daily", "SPY")


def test_no_directional_edge_hands_it_to_the_board(setup):
    led, ad = setup
    _misses(led, "DOGE-USD", "direction_wrong", 60)
    d = ad.diagnose(led)[0]
    assert d.retire and not d.untradeable
    ad.apply([d])
    assert "DOGE-USD" in ad.retiring("daily")


def test_every_cause_has_a_documented_response():
    from sigbot.tiers import Failure

    for f in Failure:
        if f is Failure.WIN:
            continue
        assert f.value in RESPONSES, f"{f.value} has no defined response"
    for _, meaning, action in RESPONSES.values():
        assert meaning and action


# ------------------------------------------------------------- the record

def test_the_horizon_is_read_back(setup):
    led, ad = setup
    assert ad.hours_for("daily", "X") == DEFAULT_HOURS
    _misses(led, "X", "magnitude_short", 60)
    ad.apply(ad.diagnose(led))
    assert ad.hours_for("daily", "X") == DEFAULT_HOURS + 12


def test_every_change_keeps_its_evidence(setup):
    led, ad = setup
    _misses(led, "NVDA", "reversal", 55)
    ad.apply(ad.diagnose(led))
    row = ad.history()[0]
    assert row["symbol"] == "NVDA" and row["cause"] == "reversal"
    assert row["n_misses"] == 55 and row["share"] >= MIN_SHARE
    assert row["reason"]


def test_explain_is_readable_and_honest_when_empty(setup):
    led, ad = setup
    empty = ad.explain()
    assert "No adaptations yet" in empty and str(MIN_MISSES) in empty
    _misses(led, "NVDA", "magnitude_short", 60)
    ad.apply(ad.diagnose(led))
    text = ad.explain()
    assert "NVDA" in text and "misses were" in text and "Horizon" in text


def test_unexplained_misses_change_nothing(setup):
    """A cause the price path cannot account for is not a cause."""
    led, ad = setup
    for _ in range(60):
        pid = led.record("daily", "ZZZ", "BUY", 0.6, 0.02, 0.0, horizon_hours=-1)
        led.resolve(pid, 100.0)
    assert [d for d in ad.diagnose(led) if d.changes_anything] == []
