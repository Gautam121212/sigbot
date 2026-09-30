"""Broker reconciliation — broker is truth, reconciliation never trades.

Covers all 10 required scenarios: partial fills, stale state, duplicate orders,
unknown orders, missing orders, cash mismatch, position mismatch, idempotency,
pause-on-drift and recovery after reconciliation."""
from datetime import datetime, timedelta, timezone

from sigbot.broker_reconciliation import (
    Broker, BrokerOrder, BrokerSnapshot, DiscrepancyType, FakeBroker,
    Reconciler, SigbotBelief, SystemState, firewall_allows_trading,
    resume_after_recovery)

NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _clock():
    return NOW


def _belief(positions=None, cash=50000.0, order_ids=frozenset(), submitted=None):
    return SigbotBelief(positions=positions or {"AAPL": 100},
                        cash=cash, open_client_order_ids=order_ids,
                        submitted_orders=submitted or {})


def _snap(positions=None, cash=50000.0, open_orders=(), recent=(), as_of=NOW):
    return BrokerSnapshot(as_of=as_of, positions=positions or {"AAPL": 100},
                          cash=cash, open_orders=open_orders, recent_orders=recent)


def _rec():
    return Reconciler(now_fn=_clock)


# ── clean baseline ──────────────────────────────────────────────────────────
def test_clean_state_stays_active():
    res = _rec().reconcile(_belief(), _snap())
    assert res.resulting_state == SystemState.TRADING_ACTIVE
    assert not res.discrepancies
    assert firewall_allows_trading(res.resulting_state)


# ── 1. position mismatch (broker wins) ──────────────────────────────────────
def test_position_mismatch_pauses_and_broker_wins():
    res = _rec().reconcile(_belief(positions={"AAPL": 100}),
                           _snap(positions={"AAPL": 63}))
    assert res.is_paused()
    d = [x for x in res.material() if x.kind == DiscrepancyType.POSITION_DRIFT][0]
    assert d.expected == "100" and d.observed == "63"   # broker authoritative
    assert not firewall_allows_trading(res.resulting_state)


# ── 2. cash mismatch ────────────────────────────────────────────────────────
def test_cash_mismatch_pauses():
    res = _rec().reconcile(_belief(cash=50000), _snap(cash=48000))
    assert res.is_paused()
    assert any(d.kind == DiscrepancyType.CASH_DRIFT for d in res.material())


# ── 3. partial fill ─────────────────────────────────────────────────────────
def test_partial_fill_detected():
    o = BrokerOrder("O1", "MSFT", 100, 60, 300.0, "partial", "C1")
    res = _rec().reconcile(_belief(order_ids=frozenset({"C1"}),
                                   submitted={"C1": 100}),
                           _snap(open_orders=(o,)))
    assert any(d.kind == DiscrepancyType.PARTIAL_FILL for d in res.material())
    assert res.is_paused()


# ── 4. stale broker state ───────────────────────────────────────────────────
def test_stale_broker_state_pauses():
    old = NOW - timedelta(seconds=600)
    res = _rec().reconcile(_belief(), _snap(as_of=old))
    assert any(d.kind == DiscrepancyType.STALE_BROKER_STATE for d in res.material())
    assert res.is_paused()


# ── 5. duplicate order ──────────────────────────────────────────────────────
def test_duplicate_order_detected():
    o1 = BrokerOrder("O1", "MSFT", 100, 100, 300.0, "filled", "C1")
    o2 = BrokerOrder("O2", "MSFT", 100, 100, 300.0, "filled", "C1")  # same client id
    res = _rec().reconcile(_belief(order_ids=frozenset({"C1"}),
                                   submitted={"C1": 100}),
                           _snap(recent=(o1, o2)))
    assert any(d.kind == DiscrepancyType.DUPLICATE_ORDER for d in res.material())


# ── 6. unknown broker order ─────────────────────────────────────────────────
def test_unknown_broker_order_detected():
    o = BrokerOrder("O9", "TSLA", 50, 50, 200.0, "filled", "NOT_MINE")
    res = _rec().reconcile(_belief(), _snap(recent=(o,)))
    assert any(d.kind == DiscrepancyType.UNKNOWN_BROKER_ORDER for d in res.material())
    assert res.is_paused()


# ── 7. missing order ────────────────────────────────────────────────────────
def test_missing_order_detected():
    # SIGBOT thinks C7 is open, broker has never heard of it
    res = _rec().reconcile(_belief(order_ids=frozenset({"C7"}),
                                   submitted={"C7": 100}),
                           _snap())
    assert any(d.kind == DiscrepancyType.MISSING_ORDER for d in res.material())
    assert res.is_paused()


# ── 8. rejected / cancelled ─────────────────────────────────────────────────
def test_rejected_order_detected():
    o = BrokerOrder("O1", "MSFT", 100, 0, 0.0, "rejected", "C1")
    res = _rec().reconcile(_belief(order_ids=frozenset({"C1"}),
                                   submitted={"C1": 100}),
                           _snap(recent=(o,)))
    assert any(d.kind == DiscrepancyType.REJECTED_OR_CANCELLED
               for d in res.material())


# ── 9. idempotency ──────────────────────────────────────────────────────────
def test_idempotent_no_duplicate_ledger_entries():
    r = _rec()
    belief = _belief(positions={"AAPL": 100})
    snap = _snap(positions={"AAPL": 63})
    r.reconcile(belief, snap)
    n_after_first = len(r.ledger)
    # re-run against identical state
    r.reconcile(belief, snap)
    r.reconcile(belief, snap)
    assert len(r.ledger) == n_after_first          # no duplicates


def test_idempotent_same_result():
    r = _rec()
    belief = _belief(positions={"AAPL": 100})
    snap = _snap(positions={"AAPL": 63})
    r1 = r.reconcile(belief, snap)
    r2 = r.reconcile(belief, snap)
    assert r1.resulting_state == r2.resulting_state
    assert r1.belief_hash == r2.belief_hash
    assert r1.snapshot_hash == r2.snapshot_hash


# ── 10. pause-on-drift and recovery ─────────────────────────────────────────
def test_pause_on_drift_then_recover_when_clean():
    r = _rec()
    # drift -> paused
    drift = r.reconcile(_belief(positions={"AAPL": 100}),
                        _snap(positions={"AAPL": 63}))
    assert drift.is_paused()
    # cannot resume while drift is still material
    assert resume_after_recovery(drift) == SystemState.TRADING_PAUSED
    # operator fixes: broker and belief now agree -> clean reconcile
    clean = r.reconcile(_belief(positions={"AAPL": 63}),
                        _snap(positions={"AAPL": 63}))
    assert clean.resulting_state == SystemState.TRADING_ACTIVE
    assert resume_after_recovery(clean) == SystemState.TRADING_ACTIVE


def test_recovery_cannot_be_forced_over_open_drift():
    r = _rec()
    drift = r.reconcile(_belief(positions={"AAPL": 100}),
                        _snap(positions={"AAPL": 63}))
    # even calling resume, an open material drift keeps it paused
    assert resume_after_recovery(drift) == SystemState.TRADING_PAUSED


# ── reconciliation never trades (structural) ────────────────────────────────
def test_reconciler_has_no_order_placing_method():
    r = _rec()
    assert not hasattr(r, "place_order")
    assert not hasattr(r, "submit_order")
    assert not hasattr(r, "correct_drift")


def test_fake_broker_conforms_to_interface():
    fb = FakeBroker(_snap())
    assert isinstance(fb, Broker)
    assert fb.snapshot().positions == {"AAPL": 100}


# ── ledger records full context ─────────────────────────────────────────────
def test_ledger_records_hashes_and_transition():
    r = _rec()
    r.reconcile(_belief(positions={"AAPL": 100}), _snap(positions={"AAPL": 63}))
    ev = r.ledger.all()[0]
    assert ev.belief_hash and ev.snapshot_hash
    assert ev.resulting_state == SystemState.TRADING_PAUSED
    assert "position_drift" in ev.discrepancy_kinds
    assert ev.broker_as_of == NOW
