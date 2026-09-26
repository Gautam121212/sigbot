"""Professional execution layer — sizing and exits."""
from sigbot.execution import HOLD_DAYS, plan_trade


def test_proven_signals_get_more_size_than_risky():
    proven = plan_trade(style="reversion", proven=True, atr_pct=0.03)
    risky = plan_trade(style="news", proven=False, atr_pct=0.03)
    assert proven.size_pct > risky.size_pct


def test_wider_atr_means_smaller_position():
    tight = plan_trade(style="reversion", proven=True, atr_pct=0.02)
    wide = plan_trade(style="reversion", proven=True, atr_pct=0.10)
    assert wide.size_pct < tight.size_pct     # wider stop -> smaller size, same risk


def test_reversion_adds_to_the_loser_not_the_winner():
    """The tested finding: mean-reversion scales the underwater trade."""
    p = plan_trade(style="reversion", proven=True, atr_pct=0.03)
    assert "UNDERWATER" in p.scale_rule and "NOT the winner" in p.scale_rule


def test_momentum_adds_to_the_winner():
    p = plan_trade(style="momentum", proven=True, atr_pct=0.03)
    assert "WINNER" in p.scale_rule


def test_reversion_exits_faster_than_momentum():
    """The edge is front-loaded for reversion; momentum runs longer."""
    assert HOLD_DAYS["reversion"] < HOLD_DAYS["momentum"]
    assert HOLD_DAYS["news"] <= 3            # news decays fastest


def test_position_never_exceeds_ten_percent():
    # even a tiny ATR can't blow size past the cap
    p = plan_trade(style="reversion", proven=True, atr_pct=0.001)
    assert p.size_pct <= 10.0
