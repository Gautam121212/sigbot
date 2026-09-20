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


def test_risk_and_capital_are_separate_limits():
    """A dry run of thirty simultaneous signals took four positions at 4%
    total risk — correct — while committing 67% of the account. Six would have
    needed more cash than exists. Tight stops make positions cheap in risk and
    expensive in capital."""
    from sigbot.risk import MAX_DEPLOYED

    full = RiskState(equity=100_000, deployed=100_000 * MAX_DEPLOYED)
    d = decide(full, entry_price=100.0, stop_price=95.0)
    assert not d.allowed
    assert "no cash left" in d.reason


def test_a_partly_funded_book_gets_a_smaller_position_not_a_refusal():
    """Trimming to the cash available is right; refusing outright would skip
    a valid trade over an arithmetic detail."""
    from sigbot.risk import MAX_DEPLOYED

    nearly = RiskState(equity=100_000, deployed=100_000 * MAX_DEPLOYED - 1_000)
    d = decide(nearly, entry_price=100.0, stop_price=95.0)
    assert d.allowed and d.size <= 1_000


def test_a_market_wide_day_does_not_become_one_enormous_bet():
    """The real worst day fired 263 signals at once, and 67% of an average
    day's signals come from a single sector. Six positions at 1% is 6% of risk
    only if they are six different bets."""
    from sigbot.risk import MAX_OPEN_POSITIONS, MAX_PER_SECTOR

    state = RiskState(equity=100_000)
    sector_counts: dict[str, int] = {}
    taken = 0
    for i in range(30):
        sector = "tech" if i < 15 else "energy"
        d = decide(RiskState(equity=state.equity, open_risk=state.open_risk,
                             deployed=state.deployed,
                             open_positions=state.open_positions,
                             sector_positions=sector_counts.get(sector, 0)),
                   entry_price=100.0, stop_price=94.0)
        if not d.allowed:
            continue
        taken += 1
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        state = RiskState(equity=state.equity,
                          open_risk=state.open_risk + d.risk_fraction,
                          deployed=state.deployed + d.size,
                          open_positions=state.open_positions + 1)

    assert taken <= MAX_OPEN_POSITIONS
    assert all(v <= MAX_PER_SECTOR for v in sector_counts.values())
    assert state.open_risk <= MAX_PORTFOLIO_HEAT + 1e-9
    assert state.deployed <= 100_000
