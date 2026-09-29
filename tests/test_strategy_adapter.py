"""Strategy adapter — common contract with the two structural invariants."""
from sigbot.strategy_adapter import (
    DeclaredClaims, NormalizedSignal, Strategy, StrategyMetadata,
    TargetPosition, claim_vs_delivery, normalize, to_orders)


class _Demo:
    def metadata(self):
        return StrategyMetadata("DEMO", "US", DeclaredClaims(0.6, 0.065, 63, "demo"))
    def target_positions(self, as_of_date):
        return [TargetPosition("A", 0.5), TargetPosition("B", 0.5)]


class _Greedy:
    def metadata(self):
        return StrategyMetadata("GREEDY", "US", DeclaredClaims())
    def target_positions(self, as_of_date):
        return [TargetPosition("A", 1.0), TargetPosition("B", 1.0)]   # gross 2.0


def test_demo_conforms_to_protocol():
    assert isinstance(_Demo(), Strategy)


def test_invariant1_no_leverage_smuggling():
    """A strategy proposing gross 2.0 is normalized to 1.0 on ingestion."""
    sig = normalize(_Greedy(), "2024-01-15")
    assert abs(sig.total_gross_weight - 1.0) < 1e-9


def test_invariant2_declared_claims_are_never_trusted():
    """Self-reported confidence/return are structurally untrusted."""
    c = DeclaredClaims(declared_confidence=0.99, declared_expected_return=0.50)
    assert not c.is_trustworthy()


def test_claim_vs_delivery_flags_overclaim():
    """The one legitimate use of declared numbers: testing them against reality."""
    cvd = claim_vs_delivery(DeclaredClaims(declared_expected_return=0.20), 0.03)
    assert cvd["overclaimed"] == 1.0
    assert cvd["claim_minus_delivery"] > 0.15


def test_contract_has_no_outcome_field():
    """Invariant 1 structurally: the metadata carries no realized-return field."""
    md = _Demo().metadata()
    assert not hasattr(md, "realized_return")
    assert not hasattr(md, "backtest_cagr")


def test_to_orders_produces_deltas_for_firewall():
    sig = normalize(_Demo(), "2024-01-15")
    orders = to_orders(sig, equity=100000, current_positions={"A": 10000})
    # A: target 50k - current 10k = 40k; B: 50k - 0 = 50k
    d = dict(orders)
    assert abs(d["A"] - 40000) < 1e-6
    assert abs(d["B"] - 50000) < 1e-6


def test_full_pipeline_adapter_to_firewall():
    """End-to-end: strategy intentions become firewall-checked orders."""
    from datetime import time

    from sigbot.risk_firewall import (
        FirewallLimits, OrderRequest, PortfolioState, check)
    sig = NormalizedSignal("INFL", "2024-01-15",
                           [TargetPosition("NVDA", 0.4)], DeclaredClaims())
    orders = to_orders(sig, 100000, {})
    st = PortfolioState(equity=100000, positions={}, sector_of={"NVDA": "TECH"})
    sym, val = orders[0]
    d = check(OrderRequest(sym, val, 10, time(10, 0)), st, FirewallLimits())
    # strategy wanted 40%; firewall caps the single order at 5%
    assert d.approved_value <= 5000
