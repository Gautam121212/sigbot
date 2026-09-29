"""Deterministic risk firewall — the control layer between strategy and broker."""
from datetime import time

from sigbot.risk_firewall import (
    FirewallLimits, OrderRequest, PortfolioState, check, describe)


def _state(**kw):
    base = dict(equity=100000.0, positions={}, sector_of={})
    base.update(kw)
    return PortfolioState(**base)


def test_normal_order_passes_unchanged():
    d = check(OrderRequest("MSFT", 4000, 10, time(10, 0)), _state(), FirewallLimits())
    assert d.approved and d.approved_value == 4000


def test_oversized_order_is_reduced_never_enlarged():
    d = check(OrderRequest("MSFT", 9000, 10, time(10, 0)), _state(), FirewallLimits())
    assert d.approved and d.approved_value == 5000  # 5% of 100k
    assert d.approved_value < 9000                  # only reduces


def test_kill_switch_blocks_everything():
    d = check(OrderRequest("MSFT", 100, 1, time(10, 0)),
              _state(kill_switch=True), FirewallLimits())
    assert not d.approved


def test_daily_loss_limit_halts_trading():
    d = check(OrderRequest("MSFT", 1000, 10, time(10, 0)),
              _state(day_pnl=-3500), FirewallLimits())
    assert not d.approved
    assert "daily loss" in d.reasons[0]


def test_slippage_cap_rejects():
    d = check(OrderRequest("MSFT", 1000, 80, time(10, 0)), _state(), FirewallLimits())
    assert not d.approved


def test_outside_hours_rejects():
    d = check(OrderRequest("MSFT", 1000, 10, time(3, 0)), _state(), FirewallLimits())
    assert not d.approved


def test_asset_scope_enforced():
    lim = FirewallLimits(allowed_assets=frozenset({"AAPL"}))
    d = check(OrderRequest("MSFT", 1000, 10, time(10, 0)), _state(), lim)
    assert not d.approved


def test_position_cap_reduces():
    st = _state(positions={"MSFT": 9000}, sector_of={"MSFT": "TECH"})
    d = check(OrderRequest("MSFT", 5000, 10, time(10, 0)), st, FirewallLimits())
    # position cap 10% = 10k, already 9k, room = 1k
    assert d.approved_value <= 1000


def test_leverage_never_exceeds_gross_cap():
    st = _state(positions={"A": 50000, "B": 45000}, sector_of={"A": "X", "B": "Y"})
    d = check(OrderRequest("C", 20000, 10, time(10, 0)), st, FirewallLimits())
    # gross already 95k, cap 100k, room 5k
    assert d.approved_value <= 5000


def test_describe_states_the_moat():
    out = describe()
    assert "NOT permission to trade" in out
    assert "never" in out.lower()
