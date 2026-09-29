"""Reality engine — SIGBOT's independent P&L judge (measures execution gaps)."""
from sigbot.reality_engine import CostModel, SimTrade, describe, simulate


def test_realistic_is_below_idealized():
    """The core: costs make SIGBOT's number lower than the repo's claim."""
    trades = [SimTrade(f"S{i}", 0.08, 50000, 2_000_000) for i in range(20)]
    r = simulate(trades)
    assert r.realistic_return_pct < r.idealized_return_pct
    assert r.gap_pct() > 0


def test_liquidity_gap_caps_oversized_orders():
    """G11: an order bigger than max ADV fraction only partly fills."""
    # order 500k vs ADV 1M, max 5% = 50k -> only 10% fills
    trades = [SimTrade("ILL", 0.15, 500000, 1_000_000)]
    r = simulate(trades)
    assert r.liquidity_capped_trades == 1
    assert r.gap_breakdown["G11_liquidity"] > 0


def test_market_impact_scales_with_order_size():
    """G10: bigger orders relative to ADV cost more impact."""
    small = simulate([SimTrade("S", 0.05, 10000, 5_000_000)])
    big = simulate([SimTrade("B", 0.05, 200000, 5_000_000)])
    assert big.gap_breakdown["G10_impact"] > small.gap_breakdown["G10_impact"]


def test_next_bar_execution_costs_edge():
    """G7: filling next-bar gives up some signal-bar edge."""
    with_nb = simulate([SimTrade("X", 0.10, 10000, 5_000_000)],
                       CostModel(next_bar_execution=True))
    without = simulate([SimTrade("X", 0.10, 10000, 5_000_000)],
                       CostModel(next_bar_execution=False))
    assert with_nb.realistic_return_pct < without.realistic_return_pct


def test_gap_is_attributable_not_asserted():
    """Every gap has a measured cost, so the weakness is proven not claimed."""
    trades = [SimTrade("S", 0.08, 300000, 1_000_000) for _ in range(10)]
    r = simulate(trades)
    # the gap breakdown sums (roughly) to the total cost
    named = sum(r.gap_breakdown.values())
    assert abs(named - r.total_cost_pct) < 0.5   # attribution accounts for it


def test_describe_states_analyst_vs_judge():
    out = describe()
    assert "AI = analyst" in out
    assert "judge" in out
