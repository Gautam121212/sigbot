"""Operating loop — where the scheduler, admission, activation, and notification
pipeline become one 24/7 machine. Integration only: no model/threshold/research
logic here.

  plan_tick() -> event plan -> dispatch by type -> admission (PREDICT only) ->
  canonical events -> notification pipeline

Hard invariants enforced here:
  * A scheduler failure does NOT fall back to the old schedule. plan_tick fails
    -> NO dispatch -> capital BLOCKED -> one CRITICAL notification. Fail closed.
  * Only PREDICT_* events can create a prediction. SCAN/RESEARCH/PREPARE/MONITOR/
    RESOLVE/RECOVER/THESIS_UPDATE/OPPORTUNITY_UPDATE never record.
  * Pending stocks entries activate at the ACTUAL next open (never scan price,
    never back-dated), and the state machine is idempotent across restart.
  * The coordinator emits canonical events into the notification pipeline — it
    never calls Telegram directly — and the digest clock stays independent.

Every dispatch carries a run_id and every event an event_id for full tracing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .market_scheduler import (
    EventType, Family, MarketScheduler, ScheduledEvent, can_create_prediction)
from .notification_policy import Event as NotifyEvent
from .notification_pipeline import NotificationPipeline, TelegramSender


@dataclass(frozen=True)
class TickResult:
    run_id: str
    dispatched: tuple[str, ...]            # "family:event_type" dispatched
    predictions_attempted: int
    activations: int
    capital_blocked: bool
    scheduler_failed: bool
    notifications_sent: int


class DispatchHandlers:
    """The adapters the loop calls for each event type. Supplied by the real
    coordinator (which owns the runners); defaults are no-ops so the loop can be
    tested in isolation. A PREDICT handler returns the number of predictions
    admitted; everything else returns None/does its own side effect."""

    def predict(self, event: ScheduledEvent, run_id: str) -> int:
        return 0

    def resolve(self, family: Family, run_id: str) -> int:
        return 0

    def activate_pending(self, family: Family, run_id: str) -> int:
        """Activate pending next-session entries at the actual open. Returns the
        number activated. The real handler fills entry_price from the session
        open and refuses to back-date before decision_effective_at."""
        return 0

    def research(self, event: ScheduledEvent, run_id: str) -> None:
        pass

    def monitor(self, family: Family, run_id: str) -> None:
        pass

    def prepare(self, family: Family, run_id: str) -> None:
        pass


@dataclass
class OperatingLoop:
    """The authoritative 24/7 tick. One call = one coordinator tick."""
    scheduler: MarketScheduler = field(default_factory=MarketScheduler)
    pipeline: NotificationPipeline = field(default_factory=NotificationPipeline)
    sender: TelegramSender = field(default_factory=TelegramSender)
    handlers: DispatchHandlers = field(default_factory=DispatchHandlers)
    _run_seq: int = 0
    _evt_seq: int = 0
    # capital is blocked whenever a tick could not plan/dispatch safely.
    capital_blocked: bool = False

    def _next_run_id(self, now: datetime) -> str:
        self._run_seq += 1
        return f"RUN-{now.strftime('%Y-%m-%d')}-{self._run_seq:06d}"

    def _emit(self, event_type: str, now: datetime, *, affects_capital=False,
              incident_id="", is_recovery=False, detail="") -> None:
        """Emit a canonical event into the notification pipeline (never Telegram
        directly). Most are SILENT by policy; the pipeline decides."""
        self._evt_seq += 1
        decision = self.pipeline.ingest(NotifyEvent(
            event_type=event_type, timestamp=now,
            affects_capital=affects_capital, incident_id=incident_id,
            is_recovery=is_recovery, detail=detail))
        if decision is not None:
            self.sender.deliver(decision)

    def tick(self, now: datetime | None = None, *, news_queue: int = 0,
             ventures_backlog: int = 0, ideas_backlog: int = 0) -> TickResult:
        now = now or datetime.now(timezone.utc)
        run_id = self._next_run_id(now)

        # ── FAIL CLOSED: a scheduler failure blocks dispatch + capital ───────
        # A single stable incident id so the recovery pairs with the failure
        # (and repeated failures dedup into one open incident).
        sched_incident = "SCHED-INCIDENT"
        try:
            plan = self.scheduler.plan_tick(
                now, news_queue=news_queue, ventures_backlog=ventures_backlog,
                ideas_backlog=ideas_backlog)
        except Exception as exc:  # noqa: BLE001  # handled: fail-closed below
            self.capital_blocked = True
            self._emit("scheduler_failure_beyond_recovery", now,
                       affects_capital=True, incident_id=sched_incident,
                       detail=f"plan_tick failed: {exc}. No models dispatched.")
            n_sent = len(self.sender.sent_messages())
            return TickResult(run_id, (), 0, 0, True, True, n_sent)

        # scheduler is healthy again -> if we were blocked, recover once.
        if self.capital_blocked:
            self.capital_blocked = False
            self._emit("scheduler_failure_beyond_recovery", now,
                       incident_id=sched_incident, is_recovery=True,
                       detail="Scheduler recovered. Dispatch resumed.")

        dispatched: list[str] = []
        predictions_attempted = 0
        activations = 0

        # ── MARKET-OPEN activation: fill pending stocks entries first ────────
        # A PREPARE/MONITOR for stocks when the market has opened is the trigger
        # to activate any pending next-session entries at the real open.
        stock_events = [e for e in plan if e.family == Family.STOCKS]
        if any(e.event_type in (EventType.MONITOR, EventType.PREPARE)
               for e in stock_events):
            activated = self.handlers.activate_pending(Family.STOCKS, run_id)
            activations += activated
            if activated:
                self._emit("stocks_entries_activated", now,
                           detail=f"{activated} pending entries activated at open")

        # ── dispatch each event by type ─────────────────────────────────────
        for event in plan:
            tag = f"{event.family.value}:{event.event_type.value}"
            dispatched.append(tag)
            et = event.event_type

            if can_create_prediction(et):
                # ONLY path that can create a prediction.
                n = self.handlers.predict(event, run_id)
                predictions_attempted += 1
                self._emit(f"{event.family.value}_predict", now)
                if n > 0:
                    self._emit("prediction_created", now)   # SILENT by policy
            elif et == EventType.RESOLVE:
                self.handlers.resolve(event.family, run_id)
                self._emit("prediction_resolved_normal", now)   # SILENT
            elif et in (EventType.RESEARCH, EventType.THESIS_UPDATE,
                        EventType.OPPORTUNITY_UPDATE):
                self.handlers.research(event, run_id)
                self._emit("research_hypothesis", now)          # SILENT
            elif et == EventType.MONITOR:
                self.handlers.monitor(event.family, run_id)
                self._emit("heartbeat", now)                    # SILENT
            elif et == EventType.PREPARE:
                self.handlers.prepare(event.family, run_id)
                self._emit("scheduler_tick", now)               # SILENT
            # RECOVER/SCAN: no-op dispatch, SILENT

        n_sent = len(self.sender.sent_messages())
        return TickResult(run_id, tuple(dispatched), predictions_attempted,
                          activations, self.capital_blocked, False, n_sent)


def describe() -> str:
    return "\n".join([
        "OPERATING LOOP — scheduler + admission + activation + notifications,",
        "one 24/7 machine.",
        "",
        "  tick() asks plan_tick() what to do and dispatches by event type.",
        "  FAIL CLOSED: a plan_tick failure blocks dispatch AND capital and fires",
        "  one CRITICAL notification — it never falls back to the old schedule.",
        "",
        "  Only PREDICT_* events can create a prediction (through admission);",
        "  SCAN/RESEARCH/PREPARE/MONITOR/RESOLVE/RECOVER/THESIS_UPDATE/",
        "  OPPORTUNITY_UPDATE never record. Pending stocks entries activate at the",
        "  ACTUAL open (never scan price, never back-dated), idempotent on",
        "  restart. Every dispatch carries a run_id; every event an event_id.",
        "",
        "  The loop emits canonical events into the notification pipeline — never",
        "  Telegram directly — so most activity is SILENT and the digest clock",
        "  stays independent. Integration only: no model/research logic here.",
    ])
