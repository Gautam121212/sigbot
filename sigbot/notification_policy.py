"""Notification policy engine — Telegram interrupts only when it matters.

Deduplication stops REPEATS of one event; it does nothing about VARIETY. 500
distinct routine events pass dedup and become 500 messages. This engine is the
missing classifier: every event is sorted into CRITICAL / IMPORTANT /
DAILY_DIGEST / WEEKLY_DIGEST / SILENT before Telegram ever sees it, so a normal
day with thousands of scheduler/model/research events produces exactly ONE
message — the daily summary.

It consumes canonical events and CALCULATES NOTHING (no P&L/health/capital math).
It only classifies, aggregates by root-cause incident, and rate-limits.

THE RULE: Telegram interrupts you only when something materially changed, needs
your attention, or belongs in a scheduled summary. Everything else stays on the
website/audit trail.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class NotificationClass(str, Enum):
    CRITICAL = "critical"          # immediate — capital/safety/integrity
    IMPORTANT = "important"        # immediate — meaningful state change
    DAILY_DIGEST = "daily_digest"  # rolled into the once-a-day summary
    WEEKLY_DIGEST = "weekly_digest"
    SILENT = "silent"              # website/audit only — never Telegram


# ── the canonical event the engine classifies ──────────────────────────────
@dataclass(frozen=True)
class Event:
    """A canonical operational event. event_type drives classification; the
    engine never inspects free text to decide severity."""
    event_type: str
    timestamp: datetime
    affects_capital: bool = False
    incident_id: str = ""          # set for failures/recoveries that form incidents
    root_incident_id: str = ""     # if this is a downstream effect of another incident
    is_recovery: bool = False
    detail: str = ""               # for the message body only, never for routing


# ── the classification table (event_type -> class) ─────────────────────────
# CRITICAL: capital/safety/integrity/trust.
_CRITICAL = frozenset({
    "broker_position_mismatch", "unexpected_broker_state", "trading_paused",
    "model_quarantined_production", "lookahead_violation_production",
    "critical_data_failure_active_model", "scheduler_failure_beyond_recovery",
    "db_api_untrustworthy", "invalid_live_transition", "risk_firewall_failure",
    "unexpected_live_order_state",
})
# IMPORTANT: meaningful lifecycle/model/operational state changes.
_IMPORTANT = frozenset({
    "model_quarantined", "model_recovered", "lifecycle_stage_change",
    "model_paper_eligible", "model_live_candidate", "incident_recovered",
    "paper_drawdown_warning", "required_source_unavailable", "sla_missed",
})
# Everything explicitly routine -> SILENT (website/audit only).
_SILENT = frozenset({
    "model_started", "model_finished", "scheduler_tick", "heartbeat",
    "prediction_created", "research_hypothesis", "research_rejected",
    "scan_success", "data_refresh", "api_call", "db_update",
    "paper_trade_normal", "prediction_resolved_normal", "status_unchanged",
    "capital_locked_unchanged",
})
# Routine-but-countable things that belong in the daily digest.
_DAILY = frozenset({
    "paper_signal", "paper_opened", "paper_resolved", "research_generated",
    "research_oos", "research_promoted",
})


def base_class(event_type: str) -> NotificationClass:
    if event_type in _CRITICAL:
        return NotificationClass.CRITICAL
    if event_type in _IMPORTANT:
        return NotificationClass.IMPORTANT
    if event_type in _DAILY:
        return NotificationClass.DAILY_DIGEST
    # default: anything not explicitly surfaced is SILENT. New routine event
    # types are silent by default — you opt IN to interrupting, never out.
    return NotificationClass.SILENT


# ── incident state for dedup + root-cause aggregation ───────────────────────
class IncidentPhase(str, Enum):
    OPEN = "open"
    RECOVERED = "recovered"


@dataclass
class PolicyDecision:
    """What the engine decided for one event."""
    notification_class: NotificationClass
    send_now: bool                 # True = emit a Telegram message now
    suppressed_reason: str = ""    # why nothing was sent (dedup/child/cooldown/silent)


@dataclass
class NotificationPolicyEngine:
    """Classifies events, aggregates downstream failures under their root
    incident, dedups opening/recovery alerts, and rate-limits oscillation. Daily
    and weekly digests are emitted by the scheduler calling emit_daily/weekly —
    individual DAILY_DIGEST events are accumulated silently until then."""
    # incident_id -> phase
    _incidents: dict[str, IncidentPhase] = field(default_factory=dict)
    # root_incident_id -> count of downstream child alerts folded in
    _children: dict[str, int] = field(default_factory=dict)
    # oscillation: incident_id -> list of open timestamps
    _flaps: dict[str, list[datetime]] = field(default_factory=dict)
    _flap_notified: set[str] = field(default_factory=set)
    # accumulated digest counters (routine volume lives here, not in Telegram)
    _daily_counts: dict[str, int] = field(default_factory=dict)
    flap_threshold: int = 5
    flap_window: timedelta = timedelta(minutes=30)

    def classify(self, event: Event) -> PolicyDecision:
        cls = base_class(event.event_type)

        # SILENT: website/audit only — accumulate nothing, send nothing.
        if cls == NotificationClass.SILENT:
            return PolicyDecision(cls, False, "routine — website/audit only")

        # DAILY_DIGEST: count it, never interrupt.
        if cls == NotificationClass.DAILY_DIGEST:
            self._daily_counts[event.event_type] = \
                self._daily_counts.get(event.event_type, 0) + 1
            return PolicyDecision(cls, False, "rolled into daily digest")

        # From here: CRITICAL or IMPORTANT — candidate for an immediate alert.
        # Root-cause aggregation: a downstream effect of an existing open
        # incident is folded into that incident, not sent on its own.
        if event.root_incident_id and \
                self._incidents.get(event.root_incident_id) == IncidentPhase.OPEN:
            self._children[event.root_incident_id] = \
                self._children.get(event.root_incident_id, 0) + 1
            return PolicyDecision(cls, False,
                                  f"aggregated under {event.root_incident_id}")

        # Recovery of a known incident: send once, only if it was open.
        if event.is_recovery and event.incident_id:
            if self._incidents.get(event.incident_id) == IncidentPhase.OPEN:
                self._incidents[event.incident_id] = IncidentPhase.RECOVERED
                return PolicyDecision(cls, True)
            return PolicyDecision(cls, False, "recovery for non-open incident")

        # Opening of an incident: dedup — one opening alert per incident.
        if event.incident_id:
            phase = self._incidents.get(event.incident_id)
            if phase == IncidentPhase.OPEN:
                # A repeat of an already-open incident is a chatty failure, not
                # oscillation — stay silent. (True oscillation is reopen-after-
                # recovery, handled below.)
                return PolicyDecision(cls, False, "duplicate of open incident")
            # new, or previously RECOVERED and now reopening (a real flap).
            reopening = phase == IncidentPhase.RECOVERED
            self._incidents[event.incident_id] = IncidentPhase.OPEN
            if reopening:
                return self._handle_flap(event, cls)
            # first time we've seen this incident -> the opening alert
            self._flaps.setdefault(event.incident_id, []).append(event.timestamp)
            return PolicyDecision(cls, True)

        # A CRITICAL/IMPORTANT event with no incident id (a one-off state change)
        # sends once.
        return PolicyDecision(cls, True)

    def _handle_flap(self, event: Event,
                     cls: NotificationClass) -> PolicyDecision:
        """A reopen-after-recovery is a flap. Each reopen is normally its own
        IMPORTANT alert, but once an incident reopens flap_threshold times in the
        window, send ONE grouped oscillation alert and then suppress further
        reopens of that incident."""
        flaps = self._flaps.setdefault(event.incident_id, [])
        flaps.append(event.timestamp)
        recent = [t for t in flaps if event.timestamp - t <= self.flap_window]
        self._flaps[event.incident_id] = recent
        if event.incident_id in self._flap_notified:
            return PolicyDecision(cls, False, "oscillating — grouped already sent")
        if len(recent) >= self.flap_threshold:
            self._flap_notified.add(event.incident_id)
            return PolicyDecision(cls, True, "oscillation grouped alert")
        # a normal reopen below the flap threshold still alerts (it recovered,
        # now it's back — worth knowing)
        return PolicyDecision(cls, True, "reopened")

    # ── digest emission (the scheduler calls these on a clock) ──────────────
    def daily_counts(self) -> dict[str, int]:
        return dict(self._daily_counts)

    def reset_daily(self) -> None:
        self._daily_counts.clear()

    def open_incidents(self) -> list[str]:
        return [i for i, p in self._incidents.items() if p == IncidentPhase.OPEN]

    def children_of(self, incident_id: str) -> int:
        return self._children.get(incident_id, 0)

    # ── restart safety ───────────────────────────────────────────────────────
    def snapshot(self) -> dict[str, str]:
        return {i: p.value for i, p in self._incidents.items()}

    def restore(self, persisted: dict[str, str]) -> None:
        """Rebuild incident phases after a restart. An already-open incident
        stays open and will NOT re-alert (classify treats it as a repeat)."""
        self._incidents = {i: IncidentPhase(p) for i, p in persisted.items()}


def describe() -> str:
    return "\n".join([
        "NOTIFICATION POLICY ENGINE — Telegram interrupts only when it matters",
        "",
        "  Dedup stops repeats of ONE event; variety is the real problem. This",
        "  classifies every event into CRITICAL / IMPORTANT / DAILY_DIGEST /",
        "  WEEKLY_DIGEST / SILENT before Telegram sees it. A normal day with",
        "  thousands of scheduler/model/research events -> ONE message (the daily",
        "  summary).",
        "",
        "  CRITICAL (immediate): capital/safety/integrity/trust failures.",
        "  IMPORTANT (immediate): meaningful lifecycle/model/state changes.",
        "  SILENT (never): model runs, ticks, predictions, hypotheses, scans,",
        "  heartbeats, normal paper outcomes, unchanged-healthy status.",
        "",
        "  Root-cause aggregation: downstream failures of one incident fold into",
        "  it (one alert, not five). One opening + one recovery per incident.",
        "  Oscillation -> a single grouped alert past a flap threshold. New event",
        "  types are SILENT by default — you opt IN to interrupting. Calculates",
        "  nothing; consumes canonical events only; read-only.",
    ])
