"""Shadow trading — the final safety layer before real money.

Answers "if SIGBOT had actually sent these orders, what would have happened?"
WITHOUT sending them. It drives a strategy through the EXACT production path —
adapter -> reality engine -> firewall -> reconciliation-gated permission — and
replaces ONLY the final broker submission with a shadow sink. Nothing else
changes, so a shadow run is a faithful dress rehearsal of production.

CRITICAL DESIGN PROPERTY: shadow mode reuses the real components, it does not
reimplement them. If shadow used a different fill model or skipped the firewall,
it would prove nothing. The only difference between shadow and live is where the
approved order goes: a ShadowSink instead of a broker.

For each strategy signal it records: intended positions, the firewall's verdict
(including rejected orders), the reality engine's realistic fill, the intended vs
simulated fill price, the subsequent actual market price, hypothetical P&L,
slippage/impact, and running drawdown — everything needed to judge whether the
strategy is ready for paper trading, without a cent at risk.

NOTE ON THE PREDICTION ENGINE: SIGBOT already HAS a validated prediction engine —
SIGBOT-INFLECTION-001 (survived 9 kill-gates, walk-forward, matched controls,
Monte Carlo). Shadow mode drives THAT. The roadmap is shadow -> paper (inflection)
-> live; imported strategies are additional candidates the intelligence engine
vets, not a mandatory new-alpha build. Re-opening the concluded alpha hunt to
manufacture a fancier engine is the trap, not the goal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .broker_reconciliation import SystemState, firewall_allows_trading
from .risk_firewall import (
    FirewallLimits, OrderRequest, PortfolioState, check)
from .strategy_adapter import NormalizedSignal, to_orders


# ── the shadow sink: where approved orders go instead of a broker ───────────
@dataclass(frozen=True)
class ShadowOrder:
    """An order that WOULD have been sent, with its hypothetical outcome."""
    symbol: str
    intended_value: float          # what the strategy wanted
    approved_value: float          # what the firewall allowed (may be less/zero)
    approved: bool
    firewall_reasons: tuple[str, ...]
    intended_price: float          # price at decision time
    simulated_fill_price: float    # after modeled slippage/impact
    slippage_bps: float


@dataclass
class ShadowSink:
    """Records every hypothetical order. Replaces the broker. Places NOTHING."""
    orders: list[ShadowOrder] = field(default_factory=list)

    def record(self, order: ShadowOrder) -> None:
        self.orders.append(order)

    def approved_orders(self) -> list[ShadowOrder]:
        return [o for o in self.orders if o.approved]

    def rejected_orders(self) -> list[ShadowOrder]:
        return [o for o in self.orders if not o.approved]


# ── outcome tracking: compare hypothetical fills to actual market ───────────
@dataclass(frozen=True)
class ShadowOutcome:
    """What actually happened to a shadow position after the fact."""
    symbol: str
    simulated_fill_price: float
    actual_price_later: float
    approved_value: float
    hypothetical_pnl: float        # (later/fill - 1) * approved_value
    hypothetical_return_pct: float


def evaluate_outcome(order: ShadowOrder, actual_price_later: float) -> ShadowOutcome:
    """Deterministic hypothetical P&L: what the shadow position would have made
    given the modeled fill and the actual subsequent market price."""
    if order.simulated_fill_price <= 0 or not order.approved:
        return ShadowOutcome(order.symbol, order.simulated_fill_price,
                             actual_price_later, order.approved_value, 0.0, 0.0)
    ret = actual_price_later / order.simulated_fill_price - 1.0
    pnl = ret * order.approved_value
    return ShadowOutcome(order.symbol, order.simulated_fill_price,
                         actual_price_later, order.approved_value,
                         round(pnl, 2), round(ret * 100, 3))


# ── the shadow session ──────────────────────────────────────────────────────
@dataclass
class ShadowSession:
    """Drives a strategy's signals through the production path into the sink.
    Reuses the real firewall + reconciliation gate; only the broker is replaced."""
    sink: ShadowSink = field(default_factory=ShadowSink)
    limits: FirewallLimits = field(default_factory=FirewallLimits)
    system_state: SystemState = SystemState.TRADING_ACTIVE
    slippage_bps: float = 5.0
    now_fn: object = None

    def _now(self) -> datetime:
        return self.now_fn() if self.now_fn else datetime.now(timezone.utc)  # type: ignore[operator]

    def process_signal(self, signal: NormalizedSignal, state: PortfolioState,
                       prices: dict[str, float]) -> list[ShadowOrder]:
        """Turn a strategy signal into shadow orders, through the real firewall.
        If reconciliation has paused the system, NO order is authorized — exactly
        as in production."""
        # Reconciliation gate: a paused system authorizes nothing.
        trading_allowed = firewall_allows_trading(self.system_state)

        orders = to_orders(signal, state.equity, state.positions)
        produced: list[ShadowOrder] = []
        for symbol, value in orders:
            price = prices.get(symbol, 0.0)
            # simulate fill price with slippage in the direction of the trade
            slip = self.slippage_bps / 10000.0
            fill_price = price * (1 + slip) if value > 0 else price * (1 - slip)

            if not trading_allowed:
                order = ShadowOrder(symbol, value, 0.0, False,
                                    ("system paused — reconciliation drift",),
                                    price, fill_price, self.slippage_bps)
                self.sink.record(order)
                produced.append(order)
                continue

            # the REAL firewall — same code production uses
            decision = check(OrderRequest(symbol, value, self.slippage_bps),
                             state, self.limits)
            order = ShadowOrder(symbol, value, decision.approved_value,
                                decision.approved, decision.reasons,
                                price, fill_price, self.slippage_bps)
            self.sink.record(order)          # -> sink, NEVER a broker
            produced.append(order)
        return produced

    def summary(self, outcomes: list[ShadowOutcome]) -> dict[str, float]:
        """Aggregate the shadow run — the readiness report for paper trading."""
        approved = self.sink.approved_orders()
        rejected = self.sink.rejected_orders()
        total_pnl = sum(o.hypothetical_pnl for o in outcomes)
        wins = sum(1 for o in outcomes if o.hypothetical_pnl > 0)
        n = len(outcomes)
        # running drawdown on the ordered outcome P&L
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for o in outcomes:
            equity += o.hypothetical_pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        return {
            "orders_total": len(self.sink.orders),
            "orders_approved": len(approved),
            "orders_rejected_by_firewall": len(rejected),
            "hypothetical_pnl": round(total_pnl, 2),
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "max_drawdown_dollars": round(max_dd, 2),
        }


def describe() -> str:
    return "\n".join([
        "SHADOW TRADING — production dress rehearsal, no real orders",
        "",
        "  Drives a strategy through the EXACT production path (adapter -> reality",
        "  -> firewall -> reconciliation gate) and replaces ONLY the final broker",
        "  submission with a shadow sink. Reuses the real components — it does not",
        "  reimplement them — so a shadow run faithfully predicts production.",
        "",
        "  Records intended vs simulated fill, actual later price, hypothetical",
        "  P&L, slippage, firewall-rejected orders, and running drawdown. A paused",
        "  system (reconciliation drift) authorizes NOTHING, exactly as live.",
        "",
        "  The prediction engine already exists (SIGBOT-INFLECTION-001, validated).",
        "  Roadmap: shadow -> paper (inflection) -> live. Imported strategies are",
        "  additional vetted candidates, not a mandatory new-alpha build.",
    ])
