"""Daily/monthly portfolio engine — Priority 1 of the 30% roadmap."""
from sigbot.daily_portfolio_engine import (
    SUSTAINED_INFLECTION_PORTFOLIO as M, describe, portfolio_viable)


def test_edge_clears_the_gate():
    """Sharpe > 1.0 and max drawdown < 30% = worth building further sleeves on."""
    assert portfolio_viable()
    assert M.sharpe > 1.0
    assert M.max_dd < 30.0


def test_drawdown_is_real_not_the_annual_artifact():
    """The honest max drawdown is ~17.6%, NOT the annual-resolution <1%."""
    assert 10.0 < M.max_dd < 25.0


def test_metrics_are_internally_consistent():
    assert M.end > M.start                          # positive over the period
    assert M.calmar == round(M.cagr / M.max_dd, 2) or abs(M.calmar - M.cagr/M.max_dd) < 0.1


def test_describe_states_the_honest_verdict():
    out = describe()
    assert "CLEARS THE GATE" in out
    assert "17.6%" in out
    assert "not through adding indicators" in out
