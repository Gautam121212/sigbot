"""Strategy adapter — the standard interface that makes any strategy comparable.

This is what turns the risk firewall from an isolated component into a control
plane: a common contract every strategy (SIGBOT-INFLECTION-001, an imported Qlib
or FinRL strategy, an LLM agent's picks) must implement, so SIGBOT can run them
all through the SAME reality layer, validation, firewall and monitoring.

TWO STRUCTURAL INVARIANTS (the product's whole value depends on them):

1. STRATEGIES EMIT INTENTIONS, NEVER OUTCOMES. A strategy returns target
   positions/weights. It CANNOT report its own return — SIGBOT computes P&L under
   its own cost/slippage/liquidity model. This is why a GitHub "+80%" becomes
   "+16%" under SIGBOT: the strategy never gets to pass its own number through.
   The contract has no field for realized performance, by design.

2. SELF-DECLARED CONFIDENCE/EXPECTED-RETURN ARE METADATA, NOT GROUND TRUTH. A
   strategy may DECLARE its confidence and expected return, but these are the
   numbers we can least trust (the strategy marking its own homework). They are
   stored ONLY to compare what a strategy CLAIMS against what it DELIVERS (the
   strategy-health check). The portfolio optimizer and firewall must NEVER treat
   declared numbers as real. `declared_*` naming enforces this at the type level.

Everything a strategy provides is therefore either a POSITION INTENTION (acted on,
but only after the firewall) or a DECLARED CLAIM (recorded, checked, never
trusted). There is no third category.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TargetPosition:
    """An INTENTION: the strategy wants this weight. Not an order, not a P&L."""
    symbol: str
    target_weight: float                    # fraction of equity, signed


@dataclass(frozen=True)
class DeclaredClaims:
    """What a strategy CLAIMS about itself. Recorded for health-checking only —
    NEVER used by the optimizer or firewall as if it were real."""
    declared_confidence: float = 0.5        # 0-1, self-reported
    declared_expected_return: float = 0.0   # self-reported, per holding period
    declared_holding_days: int = 63
    declared_by: str = "unknown"

    def is_trustworthy(self) -> bool:
        """Always False. Declared numbers are checkable claims, not truth.
        Kept as an explicit method so no caller can forget."""
        return False


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    universe: str
    declared: DeclaredClaims
    requires_data: tuple[str, ...] = ()     # what PIT data it needs


@runtime_checkable
class Strategy(Protocol):
    """The contract. A strategy emits target positions and declares metadata.
    Note what is ABSENT: no realized_return(), no report_performance(). A
    strategy cannot tell SIGBOT how well it did — SIGBOT measures that."""

    def metadata(self) -> StrategyMetadata: ...

    def target_positions(self, as_of_date: str) -> list[TargetPosition]:
        """The strategy's desired book as of a date. Point-in-time: the strategy
        must only use data available on as_of_date. SIGBOT does not verify this
        internally — that is what the PIT-validation stage checks."""
        ...


@dataclass
class NormalizedSignal:
    """What the adapter produces after ingesting a strategy: pure intentions
    plus the (untrusted) declared claims, ready for the reality/validation
    pipeline. This is the ONLY thing downstream stages see."""
    strategy_id: str
    as_of_date: str
    positions: list[TargetPosition]
    declared: DeclaredClaims                # carried for health-check, not trusted
    total_gross_weight: float = field(init=False)

    def __post_init__(self) -> None:
        self.total_gross_weight = sum(abs(p.target_weight) for p in self.positions)


def normalize(strategy: Strategy, as_of_date: str) -> NormalizedSignal:
    """Ingest any conforming strategy into the common representation. Strips away
    everything except position intentions and declared (untrusted) claims."""
    md = strategy.metadata()
    positions = strategy.target_positions(as_of_date)
    # Enforce invariant 1: normalize weights so no strategy can smuggle leverage
    # through an unnormalized book. Gross > 1.0 is scaled to 1.0 (the firewall
    # enforces the hard cap later; this is just clean ingestion).
    gross = sum(abs(p.target_weight) for p in positions)
    if gross > 1.0:
        positions = [TargetPosition(p.symbol, p.target_weight / gross)
                     for p in positions]
    return NormalizedSignal(md.strategy_id, as_of_date, positions, md.declared)


def claim_vs_delivery(declared: DeclaredClaims,
                      measured_return: float) -> dict[str, float]:
    """Strategy-health primitive (Gap 2): compare what a strategy CLAIMED against
    what SIGBOT MEASURED. A large positive gap (claimed >> delivered) is the
    signal that a strategy is degrading or was overfit. This is the ONLY use of
    the declared numbers, and it uses them as the thing being TESTED."""
    gap = declared.declared_expected_return - measured_return
    return {
        "declared_expected": declared.declared_expected_return,
        "measured": measured_return,
        "claim_minus_delivery": round(gap, 4),
        "overclaimed": 1.0 if gap > 0.02 else 0.0,   # claimed 2pp+ above reality
    }




def to_orders(signal: NormalizedSignal, equity: float,
              current_positions: dict[str, float]) -> list[tuple[str, float]]:
    """Translate target weights into the ORDER INTENTIONS the firewall checks.
    Order value = (target_weight * equity) - current_value. These are proposals;
    every one must still pass risk_firewall.check() before reaching a broker."""
    orders: list[tuple[str, float]] = []
    for pos in signal.positions:
        target_value = pos.target_weight * equity
        current_value = current_positions.get(pos.symbol, 0.0)
        delta = target_value - current_value
        if abs(delta) > 1e-6:
            orders.append((pos.symbol, delta))
    return orders


def describe() -> str:
    return "\n".join([
        "STRATEGY ADAPTER — the common contract that makes strategies comparable",
        "",
        "  Every strategy (inflection, imported Qlib/FinRL, LLM agent) implements",
        "  the same interface, so SIGBOT runs them all through ONE reality layer,",
        "  validation, firewall and monitor.",
        "",
        "  TWO INVARIANTS (enforced structurally):",
        "    1. Strategies emit INTENTIONS (target weights), never OUTCOMES.",
        "       A GitHub '+80%' becomes '+16%' because the strategy never passes",
        "       its own return through — SIGBOT computes P&L under its own costs.",
        "    2. Declared confidence/expected-return are CHECKABLE CLAIMS, never",
        "       ground truth. Used ONLY to compare claim-vs-delivery (health),",
        "       never by the optimizer or firewall. is_trustworthy() == False.",
        "",
        "  The adapter feeds the firewall, which now has strategies to control.",
        "  This is the control plane, not the alpha: it makes strategies",
        "  comparable, testable, improvable, deployable and KILLABLE.",
    ])
