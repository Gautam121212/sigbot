"""Costs scale with liquidity and volatility, as trading desks estimate them.

A flat 0.075% a side treated a 20,000 order in a mega cap and in a thin small
cap identically. Widening the scan from 100 names to 675 added many thinner
ones, so the flat cost flattered exactly the names just added.
"""
from __future__ import annotations

import json

from sigbot.paper import (
    BASE_COST_PER_SIDE,
    COST_PCT_PER_SIDE,
    MAX_COST_PER_SIDE,
    trade_cost_per_side,
)


def _p(adv, vol):
    return json.dumps({"adv": adv, "vol": vol})


def test_thinner_names_cost_more():
    liquid = trade_cost_per_side(20_000, _p(10e9, 0.02), COST_PCT_PER_SIDE)
    thin = trade_cost_per_side(20_000, _p(3e6, 0.02), COST_PCT_PER_SIDE)
    assert thin > liquid * 3


def test_bigger_orders_cost_more_but_not_proportionally():
    """The square-root rule: four times the size costs about twice the impact."""
    small = trade_cost_per_side(10_000, _p(50e6, 0.02), 0) - BASE_COST_PER_SIDE
    large = trade_cost_per_side(40_000, _p(50e6, 0.02), 0) - BASE_COST_PER_SIDE
    assert abs(large / small - 2.0) < 1e-6


def test_more_volatile_names_cost_more():
    calm = trade_cost_per_side(20_000, _p(50e6, 0.01), COST_PCT_PER_SIDE)
    wild = trade_cost_per_side(20_000, _p(50e6, 0.05), COST_PCT_PER_SIDE)
    assert wild > calm


def test_liquid_large_caps_are_cheaper_than_the_old_flat_rate():
    """Not every correction makes results worse. The flat rate overcharged
    the most liquid names."""
    assert trade_cost_per_side(20_000, _p(10e9, 0.015), COST_PCT_PER_SIDE) < COST_PCT_PER_SIDE


def test_missing_liquidity_keeps_the_old_rate_rather_than_inventing_one():
    for payload in (None, "", "not json", _p(None, None), _p(0, 0.02)):
        assert trade_cost_per_side(20_000, payload, COST_PCT_PER_SIDE) == COST_PCT_PER_SIDE


def test_cost_is_capped():
    assert trade_cost_per_side(5e6, _p(1e5, 0.2), COST_PCT_PER_SIDE) == MAX_COST_PER_SIDE


def test_the_liquidity_recorded_with_a_trade_reaches_the_paper_book(tmp_path):
    """Through the real record -> resolve -> replay path. A feature tested only
    on hand-built rows is how risk sizing went unused for several rounds."""
    from sigbot import paper
    from sigbot.shadow import ShadowLedger

    costs = {}
    for name, adv in (("liquid", 10e9), ("thin", 3e6)):
        path = str(tmp_path / f"{name}.db")
        ledger = ShadowLedger(path)
        pid = ledger.record("stocks", "X", "BUY", 0.7, 0.05, 100.0,
                            payload=_p(adv, 0.03))
        ledger.resolve(pid, 103.0)
        costs[name] = paper.replay(path).trades[0].cost
    assert costs["thin"] > costs["liquid"] * 3, costs
