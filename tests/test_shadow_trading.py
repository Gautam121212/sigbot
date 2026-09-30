"""Shadow trading — production dress rehearsal, no real orders."""
from sigbot.broker_reconciliation import SystemState
from sigbot.risk_firewall import FirewallLimits, PortfolioState
from sigbot.shadow_trading import (
    ShadowSession, evaluate_outcome)
from sigbot.strategy_adapter import (
    DeclaredClaims, NormalizedSignal, TargetPosition)


def _signal(weights):
    return NormalizedSignal("SIGBOT-INFLECTION-001", "2024-06-01",
                            [TargetPosition(s, w) for s, w in weights.items()],
                            DeclaredClaims())


def _state(equity=100000.0, positions=None):
    return PortfolioState(equity=equity, positions=positions or {},
                          sector_of={"NVDA": "T", "CRWD": "T", "SNOW": "T",
                                     "BIG": "T"})


def test_signal_flows_through_firewall_to_sink():
    sess = ShadowSession()
    sig = _signal({"NVDA": 0.04})
    orders = sess.process_signal(sig, _state(), {"NVDA": 120.0})
    assert len(orders) == 1
    assert orders[0].approved
    assert len(sess.sink.orders) == 1          # recorded in the sink


def test_no_real_broker_call_exists():
    """Structural: the session has no broker submission path."""
    sess = ShadowSession()
    assert not hasattr(sess, "broker")
    assert not hasattr(sess, "submit_to_broker")
    assert not hasattr(sess, "place_order")


def test_firewall_rejection_recorded_not_dropped():
    """An oversized order is capped by the REAL firewall and recorded."""
    sess = ShadowSession(limits=FirewallLimits(max_order_value_pct=0.02))
    sig = _signal({"BIG": 0.50})               # wants 50%, cap is 2%
    orders = sess.process_signal(sig, _state(), {"BIG": 100.0})
    o = orders[0]
    assert o.approved_value <= 2000            # 2% of 100k
    assert o.approved_value < o.intended_value


def test_paused_system_authorizes_nothing():
    sess = ShadowSession(system_state=SystemState.TRADING_PAUSED)
    sig = _signal({"NVDA": 0.04})
    orders = sess.process_signal(sig, _state(), {"NVDA": 120.0})
    assert all(not o.approved for o in orders)
    assert "paused" in orders[0].firewall_reasons[0]


def test_slippage_applied_to_fill_price():
    sess = ShadowSession(slippage_bps=10.0)
    orders = sess.process_signal(_signal({"NVDA": 0.04}), _state(), {"NVDA": 100.0})
    # buy fills above mid by slippage
    assert orders[0].simulated_fill_price > 100.0


def test_hypothetical_pnl_positive_when_price_rises():
    sess = ShadowSession()
    orders = sess.process_signal(_signal({"NVDA": 0.04}), _state(), {"NVDA": 100.0})
    oc = evaluate_outcome(orders[0], actual_price_later=110.0)
    assert oc.hypothetical_pnl > 0
    assert oc.hypothetical_return_pct > 0


def test_hypothetical_pnl_negative_when_price_falls():
    sess = ShadowSession()
    orders = sess.process_signal(_signal({"NVDA": 0.04}), _state(), {"NVDA": 100.0})
    oc = evaluate_outcome(orders[0], actual_price_later=90.0)
    assert oc.hypothetical_pnl < 0


def test_rejected_order_has_zero_pnl():
    sess = ShadowSession(system_state=SystemState.TRADING_PAUSED)
    orders = sess.process_signal(_signal({"NVDA": 0.04}), _state(), {"NVDA": 100.0})
    oc = evaluate_outcome(orders[0], actual_price_later=200.0)
    assert oc.hypothetical_pnl == 0.0          # never filled, no P&L


def test_summary_reports_drawdown_and_winrate():
    sess = ShadowSession()
    orders = sess.process_signal(
        _signal({"NVDA": 0.04, "CRWD": 0.04, "SNOW": 0.04}),
        _state(), {"NVDA": 100.0, "CRWD": 100.0, "SNOW": 100.0})
    later = {"NVDA": 110.0, "CRWD": 105.0, "SNOW": 90.0}
    outcomes = [evaluate_outcome(o, later[o.symbol]) for o in orders if o.approved]
    s = sess.summary(outcomes)
    assert s["orders_approved"] == 3
    assert 0 <= s["win_rate"] <= 100
    assert s["max_drawdown_dollars"] >= 0


def test_uses_same_firewall_as_production():
    """The sink swap is the ONLY difference — the firewall is the real one."""
    from sigbot.shadow_trading import check as shadow_check
    from sigbot.risk_firewall import check as firewall_check
    assert shadow_check is firewall_check      # same function object
