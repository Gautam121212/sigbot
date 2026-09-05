"""Tests for the expectancy layer.

`test_seventy_percent_win_rate_requires_no_skill` is the headline: it simulates
barrier races on a driftless walk and confirms that the requested 70% win rate
is a geometry setting with zero expectancy.
"""
from __future__ import annotations

import numpy as np
import pytest

from sigbot.expectancy import (
    audit,
    breakeven_win_rate,
    expectancy_r,
    geometry_table,
    kelly_fraction,
    mechanical_win_rate,
    size_position,
    skill_edge,
    target_for_win_rate,
    trades_to_detect,
    years_to_validate,
)


# --------------------------------------------------------- the free win rate

def test_seventy_percent_win_rate_requires_no_skill():
    """Simulated barrier races on a driftless walk must reproduce 1/(1+R)."""
    rng = np.random.default_rng(0)

    def race(target_r, n=20000, vol=0.01, barrier=0.20, steps=6000):
        wins = 0
        for _ in range(n):
            x = 0.0
            for _ in range(steps):
                x += rng.normal(0, vol)
                if x >= target_r * barrier:
                    wins += 1
                    break
                if x <= -barrier:
                    break
        return wins / n

    for target in (0.43, 1.0, 2.0):
        simulated = race(target)
        assert simulated == pytest.approx(mechanical_win_rate(target), abs=0.03), (
            f"target {target}R simulated {simulated:.1%} vs theory "
            f"{mechanical_win_rate(target):.1%}"
        )
    assert mechanical_win_rate(0.4286) == pytest.approx(0.70, abs=0.005)


def test_free_win_rate_equals_breakeven_win_rate():
    """The identity the whole module rests on."""
    for R in (0.25, 0.43, 1.0, 2.5, 4.0):
        assert mechanical_win_rate(R) == breakeven_win_rate(R)
        assert expectancy_r(mechanical_win_rate(R), R) == pytest.approx(0.0, abs=1e-12)


def test_the_dial_is_invertible():
    for wr in (0.35, 0.50, 0.70, 0.85):
        R = target_for_win_rate(wr)
        assert mechanical_win_rate(R) == pytest.approx(wr)


def test_ninety_nine_percent_win_rate_is_available_and_worthless():
    """A 99% win rate is one line of configuration and zero expectancy."""
    R = target_for_win_rate(0.99)
    assert R == pytest.approx(1 / 99, abs=1e-6)
    assert expectancy_r(0.99, R) == pytest.approx(0.0, abs=1e-9)
    assert skill_edge(0.99, R) == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------------- skill

def test_same_win_rate_different_skill():
    assert skill_edge(0.70, 0.43) == pytest.approx(0.001, abs=0.002)
    assert skill_edge(0.70, 1.00) == pytest.approx(0.20, abs=0.001)


def test_expectancy_matches_the_documented_values():
    assert expectancy_r(0.70, 0.60) == pytest.approx(0.120, abs=1e-9)
    assert expectancy_r(0.70, 0.75) == pytest.approx(0.225, abs=1e-9)
    assert expectancy_r(0.40, 3.00) == pytest.approx(0.600, abs=1e-9)


def test_a_low_win_rate_can_beat_a_high_one():
    """35% at 3R beats 70% at 0.43R. This is the trend-follower's position."""
    trend = expectancy_r(0.35, 3.0)
    scalp = expectancy_r(0.70, 0.43)
    assert trend > scalp
    assert scalp == pytest.approx(0.0, abs=0.005)


# ------------------------------------------------------------ sample sizes

def test_wider_targets_are_cheaper_to_validate():
    """Counter-intuitive and important: a bigger target needs FEWER trades."""
    tight = trades_to_detect(0.70, mechanical_win_rate(0.50))
    wide = trades_to_detect(0.70, mechanical_win_rate(1.00))
    assert tight > 2000 and wide < 100
    assert tight > 10 * wide


def test_two_trades_a_week_at_a_tight_target_is_unvalidatable():
    assert years_to_validate(0.70, 0.50, trades_per_week=2.0) > 20
    assert years_to_validate(0.70, 1.00, trades_per_week=2.0) < 1.0


def test_no_edge_means_infinite_sample():
    assert trades_to_detect(0.60, 0.60) == float("inf")
    assert trades_to_detect(0.50, 0.625) == float("inf")
    assert years_to_validate(0.60, 0.60) == float("inf")


# ---------------------------------------------------------------- sizing

def test_kelly_is_zero_without_edge():
    for R in (0.5, 1.0, 2.0):
        assert kelly_fraction(mechanical_win_rate(R), R) == pytest.approx(0.0, abs=1e-12)
    assert kelly_fraction(0.30, 1.0) == 0.0, "negative edge must clip to zero"


def test_sizing_refuses_on_a_thin_sample():
    a = size_position(n_trades=12, n_wins=9, target_r=0.75)
    assert a.recommended_risk_pct == 0.0
    assert "not an estimate" in a.note


def test_sizing_refuses_when_the_bound_does_not_clear_geometry():
    # 70% over 60 trades at 0.60R: lower bound ~59%, geometry gives 62.5%.
    a = size_position(n_trades=60, n_wins=42, target_r=0.60)
    assert a.recommended_risk_pct == 0.0
    assert "does not clear" in a.note


def test_sizing_uses_the_lower_bound_not_the_point_estimate():
    a = size_position(n_trades=400, n_wins=280, target_r=1.00)
    assert a.recommended_risk_pct > 0
    assert a.conservative_kelly < a.full_kelly / 3, (
        "quarter-Kelly on the lower bound must be far below full Kelly"
    )
    assert a.recommended_risk_pct <= 2.0, "hard cap must bind"


def test_hard_cap_binds_even_on_an_enormous_edge():
    a = size_position(n_trades=5000, n_wins=4500, target_r=3.0)
    assert a.full_kelly > 0.8
    assert a.recommended_risk_pct == 2.0


def test_zero_trades_is_handled():
    a = size_position(0, 0, 1.0)
    assert a.recommended_risk_pct == 0.0 and "risk nothing" in a.note


# ------------------------------------------------------------- diagnostics

def test_audit_flags_a_system_below_its_own_geometry():
    text = audit(0.60, 0.75, 200)     # geometry gives 57.1%, but bound is low
    assert "geometry alone gives 57.1%" in text
    assert "VERDICT" in text
    losing = audit(0.50, 0.75, 500)
    assert "losing system" in losing


def test_audit_accepts_a_genuine_edge():
    assert "clears its geometry" in audit(0.70, 1.00, 400)


def test_geometry_table_renders():
    t = geometry_table()
    assert "free WR" in t and "0.43" in t


def test_invalid_inputs_are_rejected():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            mechanical_win_rate(bad)
    for bad in (0.0, 1.0, 1.5):
        with pytest.raises(ValueError):
            target_for_win_rate(bad)
