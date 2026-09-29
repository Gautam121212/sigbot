"""Deterministic risk firewall — the control layer between strategy and broker.

The one piece of the "autonomous trading system" architecture that is (a) genuine
SIGBOT moat, (b) works with the single validated strategy today, and (c) needs NO
new alpha. Every GitHub competitor treats this as an afterthought; TradingAgents'
own issue tracker shows the field still lacks hard spend/scope controls. This is
where SIGBOT is deliberately stronger.

PRINCIPLE: a forecast is NOT permission to trade. The AI/strategy proposes a
target order; this firewall — pure, deterministic, no model in the loop — decides
whether it is allowed. It can only ever REDUCE or REJECT, never enlarge. If any
check fails, the order is blocked. The firewall is the last thing before the
broker and the strategy cannot override it.

The checks are the standard production set (position, daily-loss, leverage,
asset-scope, turnover, sector, order-value, slippage, hours, kill-switch), each
a plain rule with an explicit reason string so every block is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass(frozen=True)
class FirewallLimits:
    max_position_pct: float = 0.10          # no single name > 10% of equity
    max_order_value_pct: float = 0.05       # no single order > 5% of equity
    max_daily_loss_pct: float = 0.03        # halt after -3% on the day
    max_gross_leverage: float = 1.00        # no leverage (SIGBOT is unlevered)
    max_sector_pct: float = 0.30            # no sector > 30% of equity
    max_daily_turnover_pct: float = 0.50    # no more than 50% of equity traded/day
    max_slippage_bps: float = 50.0          # reject if expected slippage > 50bps
    allowed_assets: frozenset[str] = field(default_factory=frozenset)  # empty = all
    market_open: time = time(9, 30)
    market_close: time = time(16, 0)


@dataclass
class PortfolioState:
    """The broker is the source of truth — this is the reconciled live state."""
    equity: float
    positions: dict[str, float]             # symbol -> current market value
    sector_of: dict[str, str]               # symbol -> sector
    day_pnl: float = 0.0                    # realized+unrealized on the day
    day_turnover: float = 0.0               # value traded so far today
    kill_switch: bool = False


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    value: float                            # signed: + buy, - sell
    expected_slippage_bps: float = 0.0
    now: time = time(10, 0)


@dataclass(frozen=True)
class FirewallDecision:
    approved: bool
    approved_value: float                   # may be reduced from requested
    reasons: tuple[str, ...]                # why blocked/reduced (auditable)


def check(order: OrderRequest, state: PortfolioState,
          limits: FirewallLimits) -> FirewallDecision:
    """Deterministic permission check. Returns the allowed order (possibly
    reduced or zero) plus every reason a limit bound it. Never enlarges."""
    reasons: list[str] = []

    # Hard blocks (reject entirely)
    if state.kill_switch:
        return FirewallDecision(False, 0.0, ("kill_switch active",))
    if not (limits.market_open <= order.now <= limits.market_close):
        return FirewallDecision(False, 0.0, ("outside trading hours",))
    if limits.allowed_assets and order.symbol not in limits.allowed_assets:
        return FirewallDecision(False, 0.0, (f"{order.symbol} not in allowed scope",))
    if state.day_pnl <= -limits.max_daily_loss_pct * state.equity:
        return FirewallDecision(False, 0.0, ("daily loss limit hit — trading halted",))
    if order.expected_slippage_bps > limits.max_slippage_bps:
        return FirewallDecision(False, 0.0,
            (f"expected slippage {order.expected_slippage_bps}bps > "
             f"{limits.max_slippage_bps}bps cap",))

    allowed = order.value

    # Order-value cap
    cap = limits.max_order_value_pct * state.equity
    if abs(allowed) > cap:
        reasons.append(f"order reduced to {limits.max_order_value_pct:.0%} equity cap")
        allowed = cap if allowed > 0 else -cap

    # Position cap (only binds on buys that grow a position)
    if allowed > 0:
        cur = state.positions.get(order.symbol, 0.0)
        pos_cap = limits.max_position_pct * state.equity
        if cur + allowed > pos_cap:
            room = max(0.0, pos_cap - cur)
            if room < allowed:
                reasons.append(f"position reduced to {limits.max_position_pct:.0%} cap")
                allowed = room

    # Sector cap (only on buys)
    if allowed > 0:
        sec = state.sector_of.get(order.symbol, "UNKNOWN")
        sec_val = sum(v for s, v in state.positions.items()
                      if state.sector_of.get(s) == sec)
        sec_cap = limits.max_sector_pct * state.equity
        if sec_val + allowed > sec_cap:
            room = max(0.0, sec_cap - sec_val)
            if room < allowed:
                reasons.append(f"sector {sec} reduced to {limits.max_sector_pct:.0%} cap")
                allowed = room

    # Leverage cap
    gross_after = sum(abs(v) for v in state.positions.values()) + abs(allowed)
    if gross_after > limits.max_gross_leverage * state.equity:
        room = max(0.0, limits.max_gross_leverage * state.equity
                   - sum(abs(v) for v in state.positions.values()))
        if room < abs(allowed):
            reasons.append(f"leverage reduced to {limits.max_gross_leverage:.1f}x cap")
            allowed = room if order.value > 0 else -room

    # Turnover cap
    if state.day_turnover + abs(allowed) > limits.max_daily_turnover_pct * state.equity:
        room = max(0.0, limits.max_daily_turnover_pct * state.equity - state.day_turnover)
        if room < abs(allowed):
            reasons.append("daily turnover cap reached")
            allowed = room if order.value > 0 else -room

    if abs(allowed) < 1e-9:
        return FirewallDecision(False, 0.0, tuple(reasons) or ("no room under limits",))
    return FirewallDecision(True, allowed, tuple(reasons))


def describe() -> str:
    return "\n".join([
        "DETERMINISTIC RISK FIREWALL — the control layer, not the alpha",
        "",
        "  A forecast is NOT permission to trade. The strategy proposes; this",
        "  deterministic firewall decides. It only REDUCES or REJECTS, never",
        "  enlarges, and the strategy cannot override it.",
        "",
        "  Checks (each auditable, with a reason string):",
        "    kill-switch, trading hours, asset scope, daily-loss halt, slippage",
        "    cap (hard blocks); order-value, position, sector, leverage, turnover",
        "    (reduce-to-cap).",
        "",
        "  This is SIGBOT's deliberate strength: every GitHub competitor treats",
        "  the money-moving layer as an afterthought. The firewall assumes its",
        "  strategies are fallible and protects capital regardless — which is",
        "  exactly right after 9 experiments where 8 strategies failed OOS.",
    ])
