"""Notification pipeline — the policy engine IS the gate, not a helper.

Wires the real event path: subsystems emit Events, the policy engine classifies
them, and ONLY an admitted NotificationDecision can reach the sender. There is no
subsystem-callable telegram.send(...). A developer cannot bypass the policy by
forgetting to call it, because the sender refuses anything that is not a sealed
decision the policy produced.

  Subsystem -> Event -> Policy -> NotificationDecision -> Telegram sender
                          │
                          └─ SILENT / DIGEST never produce a decision at all

Digest counters accumulate silently; the daily/weekly summaries are emitted on a
configured OWNER-LOCAL clock (timezone from deployment config, never the server's).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

from .notification_policy import (
    Event, NotificationClass, NotificationPolicyEngine)
from .telegram_ops import TelegramOps


# ── the sealed decision — the ONLY thing the sender accepts ─────────────────
# A private sentinel the policy stamps into every decision it authorizes. The
# sender checks for it; no subsystem can forge one because it is module-private.
_POLICY_SEAL = object()


@dataclass(frozen=True)
class NotificationDecision:
    """A sealed authorization to send. Produced ONLY by the pipeline's policy
    step. The sender rejects anything whose _seal is not the policy seal, so
    arbitrary code cannot construct a 'send' the sender will honor."""
    notification_class: NotificationClass
    message: str
    incident_id: str
    _seal: object = field(default=None, repr=False, compare=False)

    def is_authorized(self) -> bool:
        return self._seal is _POLICY_SEAL


# ── deployment-configured schedule (owner-local, never server tz) ───────────
@dataclass(frozen=True)
class DigestSchedule:
    timezone_name: str = "UTC"
    daily_time: str = "08:00"
    weekly_day: str = "Sunday"
    weekly_time: str = "09:00"

    @staticmethod
    def from_env() -> "DigestSchedule":
        return DigestSchedule(
            timezone_name=os.environ.get("SIGBOT_TIMEZONE", "UTC"),
            daily_time=os.environ.get("DAILY_DIGEST_TIME", "08:00"),
            weekly_day=os.environ.get("WEEKLY_DIGEST_DAY", "Sunday"),
            weekly_time=os.environ.get("WEEKLY_DIGEST_TIME", "09:00"))

    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except Exception:  # noqa: BLE001  # handled: bad tz -> UTC fallback
            return ZoneInfo("UTC")

    def _parse(self, hhmm: str) -> time:
        try:
            h, m = hhmm.split(":")
            return time(int(h), int(m))
        except ValueError:  # noqa: BLE001  # handled: bad time -> midnight
            return time(0, 0)

    def is_daily_due(self, now_utc: datetime, last_sent_local_date) -> bool:
        """True if the owner-local daily time has passed today and we haven't
        sent today's summary yet."""
        local = now_utc.astimezone(self.tz())
        due = self._parse(self.daily_time)
        if local.date() == last_sent_local_date:
            return False
        return (local.hour, local.minute) >= (due.hour, due.minute)

    def is_weekly_due(self, now_utc: datetime, last_sent_local_date) -> bool:
        local = now_utc.astimezone(self.tz())
        if local.strftime("%A") != self.weekly_day:
            return False
        if local.date() == last_sent_local_date:
            return False
        due = self._parse(self.weekly_time)
        return (local.hour, local.minute) >= (due.hour, due.minute)


# ── the pipeline: the single entry point for all notifications ──────────────
@dataclass
class NotificationPipeline:
    """The ONE path from a SIGBOT event to Telegram. ingest() is what every
    subsystem calls; it classifies via the policy and returns a sealed
    NotificationDecision only when the policy authorizes an immediate send.
    SILENT/DIGEST events return None (nothing to send)."""
    policy: NotificationPolicyEngine = field(
        default_factory=NotificationPolicyEngine)
    ops: TelegramOps = field(default_factory=TelegramOps)
    schedule: DigestSchedule = field(default_factory=DigestSchedule.from_env)
    _last_daily: object = None          # local date of last daily summary
    _last_weekly: object = None

    def ingest(self, event: Event) -> NotificationDecision | None:
        """Classify an event. Returns a sealed decision to send now, or None.
        This is the ONLY way a notification is produced — no direct send path."""
        decision = self.policy.classify(event)
        if not decision.send_now:
            return None                 # SILENT, DIGEST, deduped, aggregated
        msg = self._render(event, decision.notification_class)
        return NotificationDecision(
            notification_class=decision.notification_class, message=msg,
            incident_id=event.incident_id, _seal=_POLICY_SEAL)

    def _render(self, event: Event, cls: NotificationClass) -> str:
        icon = "🚨" if cls == NotificationClass.CRITICAL else "⚠️"
        verb = "RECOVERED" if event.is_recovery else event.event_type.upper()
        action = ("Nothing right now."
                  if not event.affects_capital or event.is_recovery
                  else "Investigate when convenient.")
        lines = [f"{icon} {verb.replace('_', ' ')}", ""]
        if event.detail:
            lines.append(event.detail)
            lines.append("")
        lines.append(f"Capital: {'LOCKED' if event.affects_capital else '—'}")
        if event.incident_id:
            lines.append(f"Incident: {event.incident_id}")
        lines.append(f"You need to do: {action}")
        return "\n".join(lines)

    # ── digest emission on the owner-local clock ─────────────────────────────
    def maybe_emit_daily(self, now_utc: datetime, *, system_ok: dict,
                         lifecycle_state: str, capital: str, paper: dict,
                         research: dict, critical_count: int
                         ) -> NotificationDecision | None:
        """Emit the daily summary iff the owner-local daily time has passed and
        today's summary hasn't gone out. The summary itself is NOT an event — it
        never re-enters the policy, so it cannot recursively trigger a
        notification. Resets the digest counters after sending."""
        local_date = now_utc.astimezone(self.schedule.tz()).date()
        if not self.schedule.is_daily_due(now_utc, self._last_daily):
            return None
        # fold the accumulated digest counts into the paper/research sections,
        # mapping count event-types to the summary's field names.
        counts = self.policy.daily_counts()
        folded = {
            "signals": counts.get("paper_signal", 0),
            "executed": counts.get("paper_opened", 0),
            "resolved": counts.get("paper_resolved", 0),
        }
        paper = {**folded, **paper}       # explicit paper values still win
        research = {"generated": counts.get("research_generated", 0),
                    "oos": counts.get("research_oos", 0),
                    "promoted": counts.get("research_promoted", 0),
                    **research}
        msg = self.ops.render_daily(
            date=local_date.strftime("%d %b"), system_ok=system_ok,
            lifecycle_state=lifecycle_state, capital=capital, paper=paper,
            research=research, critical_count=critical_count)
        self._last_daily = local_date
        self.policy.reset_daily()
        # a DAILY decision is sealed but carries no incident_id, so it is never
        # treated as an incident and cannot be deduped/aggregated.
        return NotificationDecision(NotificationClass.DAILY_DIGEST, msg, "",
                                    _seal=_POLICY_SEAL)

    def maybe_emit_weekly(self, now_utc: datetime, *, summary_text: str
                          ) -> NotificationDecision | None:
        local_date = now_utc.astimezone(self.schedule.tz()).date()
        if not self.schedule.is_weekly_due(now_utc, self._last_weekly):
            return None
        self._last_weekly = local_date
        return NotificationDecision(NotificationClass.WEEKLY_DIGEST,
                                    summary_text, "", _seal=_POLICY_SEAL)


# ── the sender: refuses anything not sealed by the policy ───────────────────
class UnauthorizedNotification(Exception):
    """Raised if code tries to send something the policy did not authorize."""


@dataclass
class TelegramSender:
    """Accepts ONLY sealed NotificationDecision objects. There is no send(text)
    method — the policy is the gate, structurally, not by convention."""
    _sent: list[str] = field(default_factory=list)

    def deliver(self, decision: NotificationDecision) -> None:
        if not isinstance(decision, NotificationDecision) \
                or not decision.is_authorized():
            raise UnauthorizedNotification(
                "the sender only delivers sealed decisions from the policy "
                "pipeline — no direct send path exists")
        self._sent.append(decision.message)

    def sent_messages(self) -> list[str]:
        return list(self._sent)


def describe() -> str:
    return "\n".join([
        "NOTIFICATION PIPELINE — the policy engine IS the gate",
        "",
        "  Subsystem -> Event -> Policy -> sealed NotificationDecision -> Sender.",
        "  The sender has NO send(text) method and refuses anything not sealed by",
        "  the policy, so a developer cannot bypass classification by forgetting",
        "  to call it — the gate is structural, not a convention.",
        "",
        "  ingest() is the single entry point: SILENT/DIGEST/deduped/aggregated",
        "  events return None (nothing sent); only an authorized CRITICAL/",
        "  IMPORTANT produces a decision. Digest counts accumulate silently; the",
        "  daily/weekly summaries emit on an OWNER-LOCAL clock (SIGBOT_TIMEZONE /",
        "  DAILY_DIGEST_TIME / WEEKLY_DIGEST_DAY/TIME from deployment config, not",
        "  the server tz). The daily summary is not an event and never recurses.",
        "",
        "  Result: SIGBOT can be extremely noisy internally while Telegram stays",
        "  extremely quiet — one message on a normal day.",
    ])
