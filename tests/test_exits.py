"""Exit rules — where the money actually was."""
from __future__ import annotations

from sigbot.exits import MAX_HOLD_BARS, STOP_ATR_MULTIPLE, explain, plan, resolve


def test_the_stop_scales_to_what_the_name_normally_does():
    """A naive fixed 5% stop returned -0.065% on the real sample because 5%
    sits inside the normal noise of names that move 4% in a day. A quiet name
    and a violent one must not get the same distance."""
    quiet = plan(entry_price=100.0, atr=1.0)
    violent = plan(entry_price=100.0, atr=5.0)

    assert quiet and violent
    assert quiet.stop_distance_pct < violent.stop_distance_pct
    assert quiet.stop_price == 100.0 - STOP_ATR_MULTIPLE * 1.0


def test_winners_are_not_capped():
    """Capping at 6xATR scored +1.360% against +1.424% for letting it run,
    and a cap is the mechanical form of selling winners early."""
    p = plan(entry_price=100.0, atr=2.0)
    assert p is not None and p.target_price is None
    assert "left to run" in p.describe()


def test_a_missing_volatility_reading_produces_no_plan():
    """A position whose stop cannot be placed has unknown risk, and the risk
    module refuses to size those. Returning None is the correct outcome."""
    assert plan(entry_price=100.0, atr=0.0) is None
    assert plan(entry_price=0.0, atr=2.0) is None
    assert plan(entry_price=1.0, atr=100.0) is None, "stop below zero"


def test_the_stop_is_checked_before_the_target():
    """Intraday order is unknowable from daily bars. Assuming the favourable
    one is how a backtest quietly inflates itself."""
    p = plan(entry_price=100.0, atr=2.0, target_multiple=2.0)
    assert p is not None
    # A bar that touched both the stop (94) and the target (104).
    ret, why = resolve(p, lows=[93.0], highs=[105.0], closes=[100.0])
    assert ret < 0 and "stopped out" in why


def test_a_trade_that_never_resolves_closes_at_the_backstop():
    p = plan(entry_price=100.0, atr=2.0)
    assert p is not None
    lows = [99.0] * 20
    highs = [101.0] * 20
    closes = [100.5] * 20
    ret, why = resolve(p, lows, highs, closes)
    assert f"{MAX_HOLD_BARS} day" in why
    assert ret > 0


def test_the_measured_numbers_are_stated_not_asserted():
    text = explain()
    assert "+0.759%" in text and "+1.424%" in text
    assert "-0.065%" in text, "the failure that nearly shipped must be recorded"
