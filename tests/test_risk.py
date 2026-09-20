"""Risk discipline — the part professionals spend most of their attention on.

Practitioner sources put it at roughly 80% of a professional's energy on risk
management and 20% on entries, with amateurs inverting it. Every model in this
system decided WHAT to trade; none decided HOW MUCH or WHEN TO STOP.
"""
from __future__ import annotations

from sigbot.risk import (
    DAILY_LOSS_LIMIT,
    LOSS_STREAK_PAUSE,
    MAX_PORTFOLIO_HEAT,
    RISK_PER_TRADE,
    RiskState,
    decide,
)


def test_a_wider_stop_buys_a_smaller_position_at_the_same_risk():
    """The whole idea. Risk is held constant and SIZE varies, rather than size
    being held constant and risk varying with volatility."""
    state = RiskState(equity=100_000)
    tight = decide(state, entry_price=100.0, stop_price=95.0)
    wide = decide(state, entry_price=100.0, stop_price=80.0)

    assert tight.allowed and wide.allowed
    assert tight.size > wide.size * 3
    assert tight.risk_fraction == wide.risk_fraction == RISK_PER_TRADE


def test_risk_is_reduced_in_drawdown_never_increased():
    """The direction every source agrees on and instinct argues against.
    Increasing to recover raises risk precisely when the evidence that
    something has changed is strongest."""
    healthy = decide(RiskState(100_000), 100.0, 95.0)
    drawn = decide(RiskState(85_000, peak_equity=100_000), 100.0, 95.0)
    deep = decide(RiskState(75_000, peak_equity=100_000), 100.0, 95.0)

    assert drawn.risk_fraction < healthy.risk_fraction
    assert deep.risk_fraction < drawn.risk_fraction


def test_a_losing_streak_pauses_new_entries():
    state = RiskState(100_000, loss_streak=LOSS_STREAK_PAUSE)
    d = decide(state, 100.0, 95.0)
    assert not d.allowed
    assert "in a row" in d.reason


def test_the_daily_loss_limit_ends_the_day():
    state = RiskState(100_000, day_pnl_pct=-DAILY_LOSS_LIMIT - 0.001)
    d = decide(state, 100.0, 95.0)
    assert not d.allowed
    assert "daily limit" in d.reason


def test_total_open_risk_is_capped_not_just_per_trade():
    """Positions that look independent stop being independent in a drawdown."""
    state = RiskState(100_000, open_risk=MAX_PORTFOLIO_HEAT)
    assert not decide(state, 100.0, 95.0).allowed


def test_a_trade_with_no_defined_loss_is_refused():
    """A trade without a known stop has no known risk and cannot be sized."""
    state = RiskState(100_000)
    assert not decide(state, 100.0, 105.0).allowed      # stop above entry
    assert not decide(state, 100.0, 99.95).allowed      # stop inside noise
    assert not decide(state, 0.0, 0.0).allowed          # no prices


def test_no_single_position_can_dominate_the_book():
    """A stop can gap through; the risk calculation assumes it will not."""
    state = RiskState(100_000)
    d = decide(state, 100.0, 99.9)   # a very tight stop implies a huge position
    if d.allowed:
        assert d.size <= 100_000 * 0.25


def test_one_percent_survives_a_streak_that_ten_percent_does_not():
    """The arithmetic the whole module exists for: at 1% a ten-trade losing
    streak costs 10% of capital; at 10% the same streak is terminal."""
    assert RISK_PER_TRADE <= 0.02, "2% is the practitioner ceiling"
    survives = (1 - RISK_PER_TRADE) ** 50
    assert survives > 0.5, "1% must survive fifty consecutive losses"
