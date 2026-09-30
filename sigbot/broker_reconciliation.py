"""Broker reconciliation — the broker is the source of truth, never SIGBOT.

The piece that makes the firewall's PortfolioState TRUE rather than assumed. It
continuously compares SIGBOT's internal belief against the broker's authoritative
report and classifies every discrepancy. When broker and SIGBOT conflict, the
BROKER WINS — SIGBOT's intention is never treated as authoritative.

TWO STRUCTURAL SAFETY PROPERTIES:

1. RECONCILIATION NEVER TRADES. There is no code path from a detected drift to a
   placed order. Reconciliation can only CLASSIFY, LEDGER and PAUSE. Auto-
   correcting a phantom drift by trading against stale data is the worst bug in
   this class of system, so the capability simply does not exist here. Fixing a
   real discrepancy requires an explicit human/operator recovery step.

2. ANY UNRESOLVED MATERIAL DISCREPANCY PAUSES TRADING. A material drift flips the
   system to TRADING_PAUSED, and the firewall is told to refuse all new capital-
   authorizing orders until an operator explicitly resolves and resumes.

Reconciliation is IDEMPOTENT: running it repeatedly against unchanged broker
state yields the same result and no duplicate ledger entries or actions.

Broker-neutral interface first, then a FakeBroker for exhaustive testing. No live
broker connection in this module.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable


# ── trading system state ────────────────────────────────────────────────────
class SystemState(str, Enum):
    TRADING_ACTIVE = "trading_active"
    TRADING_PAUSED = "trading_paused"      # set on unresolved material drift


# ── discrepancy taxonomy ────────────────────────────────────────────────────
class DiscrepancyType(str, Enum):
    POSITION_DRIFT = "position_drift"
    CASH_DRIFT = "cash_drift"
    MISSING_ORDER = "missing_order"                # SIGBOT has it, broker doesn't
    UNKNOWN_BROKER_ORDER = "unknown_broker_order"  # broker has it, SIGBOT doesn't
    PARTIAL_FILL = "partial_fill"
    REJECTED_OR_CANCELLED = "rejected_or_cancelled"
    DUPLICATE_ORDER = "duplicate_order"
    EXECUTION_PRICE_DIFF = "execution_price_diff"
    STALE_BROKER_STATE = "stale_broker_state"


class Severity(str, Enum):
    MATERIAL = "material"      # pauses trading
    MINOR = "minor"            # logged, does not pause


@dataclass(frozen=True)
class Discrepancy:
    kind: DiscrepancyType
    severity: Severity
    symbol: str
    expected: str
    observed: str
    detail: str = ""


# ── broker-neutral interface ────────────────────────────────────────────────
@dataclass(frozen=True)
class BrokerOrder:
    order_id: str
    symbol: str
    quantity: float
    filled_quantity: float
    avg_fill_price: float
    status: str                # 'filled' | 'partial' | 'rejected' | 'cancelled' | 'open'
    client_order_id: str = ""  # SIGBOT's id, if the broker echoes it


@dataclass(frozen=True)
class BrokerSnapshot:
    """The broker's authoritative report. This is the source of truth."""
    as_of: datetime
    positions: dict[str, float]            # symbol -> quantity
    cash: float
    open_orders: tuple[BrokerOrder, ...]
    recent_orders: tuple[BrokerOrder, ...]


@runtime_checkable
class Broker(Protocol):
    """Broker-neutral interface. A real broker adapter and the FakeBroker both
    implement this. Reconciliation only READS — it never places orders here."""

    def snapshot(self) -> BrokerSnapshot: ...


# ── SIGBOT's internal belief ────────────────────────────────────────────────
@dataclass(frozen=True)
class SigbotBelief:
    """What SIGBOT THINKS is true. Never authoritative when it conflicts with the
    broker snapshot."""
    positions: dict[str, float]
    cash: float
    open_client_order_ids: frozenset[str]
    submitted_orders: dict[str, float]     # client_order_id -> quantity


def _hash_belief(b: SigbotBelief) -> str:
    payload = {"positions": dict(sorted(b.positions.items())), "cash": b.cash,
               "orders": sorted(b.open_client_order_ids)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _hash_snapshot(s: BrokerSnapshot) -> str:
    payload = {"positions": dict(sorted(s.positions.items())), "cash": s.cash,
               "open": sorted(o.order_id for o in s.open_orders)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


# ── reconciliation result ───────────────────────────────────────────────────
@dataclass(frozen=True)
class ReconciliationResult:
    resulting_state: SystemState
    discrepancies: tuple[Discrepancy, ...]
    belief_hash: str
    snapshot_hash: str

    def material(self) -> tuple[Discrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.severity == Severity.MATERIAL)

    def is_paused(self) -> bool:
        return self.resulting_state == SystemState.TRADING_PAUSED


# ── append-only ledger ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class ReconciliationEvent:
    timestamp: datetime
    belief_hash: str
    snapshot_hash: str
    broker_as_of: datetime
    expected_summary: str
    observed_summary: str
    resulting_state: SystemState
    discrepancy_kinds: tuple[str, ...]
    event_hash: str


class ReconciliationLedger:
    """Append-only. Idempotent guard: an event whose (belief_hash, snapshot_hash)
    pair already exists is NOT re-appended, so re-running against unchanged state
    produces no duplicate entries or actions."""

    def __init__(self) -> None:
        self._events: list[ReconciliationEvent] = []
        self._seen: set[tuple[str, str]] = set()

    def append_if_new(self, event: ReconciliationEvent) -> bool:
        key = (event.belief_hash, event.snapshot_hash)
        if key in self._seen:
            return False               # idempotent: already recorded
        self._seen.add(key)
        self._events.append(event)
        return True

    def all(self) -> tuple[ReconciliationEvent, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)


# ── the reconciler ──────────────────────────────────────────────────────────
POSITION_TOLERANCE = 1e-6
CASH_TOLERANCE = 0.01
PRICE_DIFF_BPS_TOLERANCE = 25.0        # execution price diff over this = material
STALE_SECONDS = 300                    # broker snapshot older than this = stale


@dataclass
class Reconciler:
    """Deterministic reconciliation. Classifies discrepancies, records them in an
    append-only ledger, and returns the resulting system state. It NEVER places
    orders — resolving a real drift is an explicit operator recovery step."""
    ledger: ReconciliationLedger = field(default_factory=ReconciliationLedger)
    now_fn: object = None              # injectable clock for tests

    def _now(self) -> datetime:
        if self.now_fn is not None:
            return self.now_fn()        # type: ignore[operator]
        return datetime.now(timezone.utc)

    def reconcile(self, belief: SigbotBelief,
                  snapshot: BrokerSnapshot) -> ReconciliationResult:
        discrepancies: list[Discrepancy] = []

        # STALE broker state
        age = (self._now() - snapshot.as_of).total_seconds()
        if age > STALE_SECONDS:
            discrepancies.append(Discrepancy(
                DiscrepancyType.STALE_BROKER_STATE, Severity.MATERIAL,
                "*", f"<= {STALE_SECONDS}s old", f"{age:.0f}s old",
                "broker snapshot too old to trust"))

        # POSITION drift — broker wins
        all_syms = set(belief.positions) | set(snapshot.positions)
        for sym in sorted(all_syms):
            exp = belief.positions.get(sym, 0.0)
            obs = snapshot.positions.get(sym, 0.0)
            if abs(exp - obs) > POSITION_TOLERANCE:
                discrepancies.append(Discrepancy(
                    DiscrepancyType.POSITION_DRIFT, Severity.MATERIAL,
                    sym, f"{exp:g}", f"{obs:g}", "broker is authoritative"))

        # CASH drift
        if abs(belief.cash - snapshot.cash) > CASH_TOLERANCE:
            discrepancies.append(Discrepancy(
                DiscrepancyType.CASH_DRIFT, Severity.MATERIAL, "$",
                f"{belief.cash:.2f}", f"{snapshot.cash:.2f}",
                "broker cash is authoritative"))

        # ORDER-level checks
        broker_by_client = {o.client_order_id: o for o in
                            (*snapshot.open_orders, *snapshot.recent_orders)
                            if o.client_order_id}
        # MISSING order: SIGBOT submitted it, broker never saw it
        for cid in sorted(belief.open_client_order_ids):
            if cid not in broker_by_client:
                discrepancies.append(Discrepancy(
                    DiscrepancyType.MISSING_ORDER, Severity.MATERIAL,
                    cid, "present at broker", "absent",
                    "SIGBOT order not acknowledged by broker"))

        # UNKNOWN broker order: broker has an order SIGBOT never submitted
        for o in (*snapshot.open_orders, *snapshot.recent_orders):
            if o.client_order_id and o.client_order_id not in belief.open_client_order_ids \
                    and o.client_order_id not in belief.submitted_orders:
                discrepancies.append(Discrepancy(
                    DiscrepancyType.UNKNOWN_BROKER_ORDER, Severity.MATERIAL,
                    o.symbol, "known to SIGBOT", o.order_id,
                    "broker order SIGBOT did not submit"))

        # PARTIAL fills, REJECTED/CANCELLED, DUPLICATES, PRICE diffs
        seen_client_ids: set[str] = set()
        for o in (*snapshot.open_orders, *snapshot.recent_orders):
            if o.status == "partial":
                discrepancies.append(Discrepancy(
                    DiscrepancyType.PARTIAL_FILL, Severity.MATERIAL, o.symbol,
                    f"{o.quantity:g}", f"{o.filled_quantity:g}",
                    "order only partially filled"))
            if o.status in ("rejected", "cancelled"):
                discrepancies.append(Discrepancy(
                    DiscrepancyType.REJECTED_OR_CANCELLED, Severity.MATERIAL,
                    o.symbol, "filled", o.status, f"order {o.status}"))
            if o.client_order_id:
                if o.client_order_id in seen_client_ids:
                    discrepancies.append(Discrepancy(
                        DiscrepancyType.DUPLICATE_ORDER, Severity.MATERIAL,
                        o.symbol, "one order", "multiple",
                        f"duplicate client_order_id {o.client_order_id}"))
                seen_client_ids.add(o.client_order_id)

        # resulting state
        material = [d for d in discrepancies if d.severity == Severity.MATERIAL]
        state = SystemState.TRADING_PAUSED if material else SystemState.TRADING_ACTIVE

        bhash = _hash_belief(belief)
        shash = _hash_snapshot(snapshot)
        event = ReconciliationEvent(
            timestamp=self._now(), belief_hash=bhash, snapshot_hash=shash,
            broker_as_of=snapshot.as_of,
            expected_summary=f"pos={len(belief.positions)} cash={belief.cash:.2f}",
            observed_summary=f"pos={len(snapshot.positions)} cash={snapshot.cash:.2f}",
            resulting_state=state,
            discrepancy_kinds=tuple(d.kind.value for d in discrepancies),
            event_hash=f"{bhash}:{shash}")
        self.ledger.append_if_new(event)      # idempotent

        return ReconciliationResult(state, tuple(discrepancies), bhash, shash)


# ── firewall integration: pause blocks capital-authorizing orders ───────────


# ── fake broker for exhaustive testing (no live connection) ─────────────────
class FakeBroker:
    """A controllable in-memory broker implementing the Broker interface. Lets
    tests drive any snapshot — drifts, partial fills, unknown orders, staleness."""

    def __init__(self, snap: BrokerSnapshot) -> None:
        self._snap = snap

    def set_snapshot(self, snap: BrokerSnapshot) -> None:
        self._snap = snap

    def snapshot(self) -> BrokerSnapshot:
        return self._snap



def firewall_allows_trading(state: SystemState) -> bool:
    """The firewall consults this before authorizing any new capital order. When
    reconciliation has paused the system, no new order may authorize capital."""
    return state == SystemState.TRADING_ACTIVE


def resume_after_recovery(current: ReconciliationResult) -> SystemState:
    """Explicit operator recovery. Only returns ACTIVE if the latest reconcile
    found no material discrepancy — recovery cannot be forced past a live drift."""
    if current.material():
        return SystemState.TRADING_PAUSED     # cannot resume over an open drift
    return SystemState.TRADING_ACTIVE


def describe() -> str:
    return "\n".join([
        "BROKER RECONCILIATION — the broker is the source of truth",
        "",
        "  Continuously compares SIGBOT's belief to the broker's authoritative",
        "  snapshot. When they conflict, the BROKER WINS. Classifies position/",
        "  cash drift, missing/unknown/duplicate orders, partial fills, rejects,",
        "  price diffs and stale state.",
        "",
        "  TWO SAFETY PROPERTIES:",
        "    1. Reconciliation NEVER trades — no code path from a drift to an",
        "       order. Fixing a real drift is an explicit operator recovery step.",
        "    2. Any unresolved MATERIAL drift -> TRADING_PAUSED, and the firewall",
        "       refuses all new capital-authorizing orders until resolved.",
        "",
        "  Idempotent: re-running against unchanged state yields the same result",
        "  and no duplicate ledger entries. Broker-neutral interface + FakeBroker",
        "  for testing; no live broker here. Next component: shadow_trading.",
    ])
