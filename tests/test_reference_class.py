"""Tests for reference-class base rates and carry economics."""
from __future__ import annotations

import pytest

from sigbot.reference_class import (
    REFERENCE_DATA,
    CarryTest,
    ReferenceClass,
    assess_claim,
    storage_thesis_questions,
)


# ------------------------------------------------------------ base rates

def test_eight_x_on_a_token_is_a_tail_outcome():
    a = assess_claim(8.0, 1.0, ReferenceClass.NEW_TOKEN_1Y)
    assert a.base_rate < 0.03
    assert "TAIL" in a.verdict or "EXTRAORDINARY" in a.verdict
    assert a.total_loss_rate == pytest.approx(0.532)
    assert "total loss" in a.render()


def test_modest_claims_are_called_ordinary():
    a = assess_claim(1.25, 3.0, ReferenceClass.IPO_3Y)
    assert a.base_rate >= 0.20 and "ORDINARY" in a.verdict


def test_bigger_claims_are_rarer_monotonically():
    rates = [assess_claim(m, 3.0, ReferenceClass.IPO_3Y).base_rate
             for m in (1.25, 1.75, 4.0, 8.0, 15.0, 40.0)]
    assert rates == sorted(rates, reverse=True)
    assert rates[-1] < 0.01


def test_shorter_horizon_lowers_the_base_rate():
    long = assess_claim(8.0, 3.0, ReferenceClass.IPO_3Y).base_rate
    short = assess_claim(8.0, 0.5, ReferenceClass.IPO_3Y).base_rate
    assert short < long
    assert "shorter horizon" in assess_claim(8.0, 0.5, ReferenceClass.IPO_3Y).render()


def test_odds_against_is_reported():
    a = assess_claim(8.0, 1.0, ReferenceClass.NEW_TOKEN_1Y)
    assert a.odds_against > 30
    assert "to 1 against" in a.render()


def test_every_class_has_a_source_and_caveat():
    for rc, d in REFERENCE_DATA.items():
        assert d.source and d.caveat, rc
        assert d.exceedance and min(d.exceedance.values()) > 0


def test_claim_must_be_a_multiple():
    with pytest.raises(ValueError, match="total multiple"):
        assess_claim(0.8, 1.0, ReferenceClass.IPO_3Y)


def test_render_states_it_is_an_outside_view():
    assert "outside view" in assess_claim(4.0, 3.0, ReferenceClass.IPO_3Y).render()


# ---------------------------------------------------------------- carry

def _copper(futures=None, consensus=True) -> CarryTest:
    return CarryTest("copper", spot_price=9500.0, horizon_years=2.0,
                     storage_pct_per_year=0.03, insurance_pct_per_year=0.005,
                     financing_pct_per_year=0.08, round_trip_spread_pct=0.02,
                     futures_price=futures, thesis_is_consensus=consensus)


def test_carry_accumulates_and_sets_a_breakeven():
    c = _copper()
    assert c.annual_carry == pytest.approx(0.115)
    assert c.breakeven_rise_pct > 0.25, "two years of 11.5% carry plus spread"
    assert "just to lose nothing" in c.render()


def test_futures_below_breakeven_means_uneconomic():
    c = _copper(futures=10200.0)          # only +7.4% vs a >25% breakeven
    assert c.edge_pct < 0
    assert "UNECONOMIC" in c.render()
    assert "market must be wrong by more" in c.render()


def test_futures_above_breakeven_leaves_a_trade():
    c = _copper(futures=13500.0)
    assert c.edge_pct > 0
    assert "the trade exists" in c.render()


def test_missing_forward_price_is_called_out():
    c = _copper(futures=None)
    assert c.market_implied_rise_pct is None and c.edge_pct is None
    assert "you are guessing" in c.render()


def test_consensus_thesis_is_flagged_as_priced():
    assert "already in the spot price" in _copper(consensus=True).render()
    assert "already in the spot price" not in _copper(consensus=False).render()


def test_physical_storage_practicalities_are_stated():
    assert "warehousing" in _copper().render()


def test_thesis_questions_cover_curve_and_exit():
    qs = storage_thesis_questions("copper")
    assert any("forward curve" in q for q in qs)
    assert any("exit" in q for q in qs)
    assert any("substitution" in q for q in qs)
    assert len(qs) >= 6
