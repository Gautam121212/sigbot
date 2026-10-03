"""SIGBOT Telegram operations layer — awareness without watching the site.

Deliberately boring. Its only job: "tell me what I need to know to stay in
control while SIGBOT runs without me watching it." Not a second website, not a
second execution interface.

FOUR PROPERTIES MADE STRUCTURAL (the failure modes the blueprint names):

  1. CONSUMES, NEVER CALCULATES. Every figure Telegram shows comes from the
     canonical state objects (evidence_api, live_lifecycle). This module has NO
     P&L / Sharpe / drawdown / capital / validation math. So Website and Telegram
     can never disagree — there is one reality.

  2. INCIDENT DEDUP + RESTART-SAFE. One failure = one alert. An incident has an
     immutable id and an OPEN -> ACKNOWLEDGED -> RECOVERED lifecycle; repeated
     firings of the same open incident send nothing. On restart the service
     reconstructs current state and does NOT re-blast history.

  3. READ-ONLY. There is no /buy /sell /go_live /promote /enable_capital — not as
     a disabled stub, but absent. Telegram observes the lifecycle's LIVE gate; it
     is never a route around it.

  4. ZERO-STATE AWARE. Live figures come straight from the lifecycle's zeroed
     live record; historical numbers are never mixed into live ones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "critical"          # immediate
    IMPORTANT = "important"        # meaningful state change
    DAILY = "daily"                # one summary / day
    WEEKLY = "weekly"              # research digest


class IncidentState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RECOVERED = "recovered"


# ── the structured event (raw exceptions never reach Telegram) ──────────────
@dataclass(frozen=True)
class OpsEvent:
    """A structured operational event. The renderer turns it into plain English;
    a raw 'BrokerReconciliationError: expected != actual' never ships."""
    event_type: str
    severity: Severity
    title: str
    plain_english: str
    reason: str
    sigbot_action: str
    capital_state: str              # pulled from lifecycle — not computed here
    requires_user_action: bool
    incident_id: str                # "" for non-incident events (daily/weekly)
    timestamp: str


# ── incident ledger: dedup + lifecycle + restart-safety ─────────────────────
@dataclass
class IncidentLedger:
    """Tracks open incidents by id so the same failure fires once. Survives
    restart: rebuilt from persisted state, it knows which incidents are already
    OPEN and will not re-alert them."""
    _state: dict[str, IncidentState] = field(default_factory=dict)
    _seq: int = 0

    def next_id(self, year: int) -> str:
        self._seq += 1
        return f"INC-{year}-{self._seq:06d}"

    def should_alert_open(self, incident_id: str) -> bool:
        """True only if this incident is not already open/acknowledged — the dedup
        gate. A repeated firing of an open incident returns False (send nothing)."""
        cur = self._state.get(incident_id)
        if cur in (IncidentState.OPEN, IncidentState.ACKNOWLEDGED):
            return False
        self._state[incident_id] = IncidentState.OPEN
        return True

    def acknowledge(self, incident_id: str) -> None:
        if self._state.get(incident_id) == IncidentState.OPEN:
            self._state[incident_id] = IncidentState.ACKNOWLEDGED

    def should_alert_recovery(self, incident_id: str) -> bool:
        """Recovery fires once, only for an incident that was actually open."""
        if self._state.get(incident_id) in (IncidentState.OPEN,
                                             IncidentState.ACKNOWLEDGED):
            self._state[incident_id] = IncidentState.RECOVERED
            return True
        return False

    def open_incidents(self) -> list[str]:
        return [i for i, s in self._state.items()
                if s in (IncidentState.OPEN, IncidentState.ACKNOWLEDGED)]

    def restore(self, persisted: dict[str, str]) -> None:
        """Restart-safety: rebuild from persisted state. Already-open incidents
        stay open and will NOT re-alert (should_alert_open returns False)."""
        self._state = {i: IncidentState(s) for i, s in persisted.items()}

    def snapshot(self) -> dict[str, str]:
        return {i: s.value for i, s in self._state.items()}


# ── read-only command surface (NO trading commands exist) ───────────────────
READ_ONLY_COMMANDS = ("/status", "/today", "/research", "/issues", "/evidence")
# These are intentionally NOT defined anywhere — listed only to assert absence.
FORBIDDEN_COMMANDS = ("/buy", "/sell", "/go_live", "/promote", "/enable_capital")


@dataclass
class TelegramOps:
    """The notification + read-only command service. Renders canonical state into
    plain-English messages. Holds NO performance math and NO capital authority."""
    ledger: IncidentLedger = field(default_factory=IncidentLedger)

    # ── notifications ────────────────────────────────────────────────────────
    def render_event(self, ev: OpsEvent) -> str | None:
        """Render an event to a message, applying dedup. Returns None when dedup
        suppresses it (an already-open incident re-firing)."""
        if ev.incident_id and ev.severity == Severity.CRITICAL:
            if not self.ledger.should_alert_open(ev.incident_id):
                return None             # deduped
        icon = {"critical": "🚨", "important": "✅"}.get(ev.severity.value, "•")
        lines = [f"{icon} {ev.title}", "", ev.plain_english, "",
                 f"Reason: {ev.reason}",
                 f"SIGBOT action: {ev.sigbot_action}",
                 f"Capital: {ev.capital_state}"]
        if ev.incident_id:
            lines.append(f"Incident: {ev.incident_id}")
        lines.append(f"You need to do: "
                     f"{'see above' if ev.requires_user_action else 'nothing'}")
        return "\n".join(lines)

    def render_recovery(self, incident_id: str, title: str,
                        plain_english: str, capital_state: str) -> str | None:
        """Recovery message — fires once per incident, never if it was never open."""
        if not self.ledger.should_alert_recovery(incident_id):
            return None
        return "\n".join([f"✅ {title}", "", plain_english,
                          f"Capital: {capital_state}",
                          f"Incident: {incident_id} (recovered)"])

    # ── daily / weekly summaries (consume canonical facts) ──────────────────
    def render_daily(self, *, date: str, system_ok: dict[str, bool],
                     lifecycle_state: str, capital: str,
                     paper: dict[str, object], research: dict[str, int],
                     critical_count: int) -> str:
        """All values are passed in from canonical sources — this method does no
        arithmetic beyond formatting what it's given."""
        sys_lines = [f"{'✅' if ok else '🚨'} {k.capitalize()} "
                     f"{'healthy' if ok else 'FAILED'}"
                     for k, ok in system_ok.items()]
        return "\n".join([
            "SIGBOT — DAILY SUMMARY", date, "", "SYSTEM", *sys_lines, "",
            f"STATE  {lifecycle_state}", f"CAPITAL  {capital}", "", "PAPER",
            f"Signals: {paper.get('signals', 0)}",
            f"Executed: {paper.get('executed', 0)}",
            f"Skipped: {paper.get('skipped', 0)}",
            f"Expired: {paper.get('expired', 0)}",
            f"Paper result: {paper.get('result', '—')}",
            f"Drawdown: {paper.get('drawdown', '—')}", "", "RESEARCH",
            f"Generated: {research.get('generated', 0)}  "
            f"Rejected: {research.get('rejected', 0)}  "
            f"Testing: {research.get('testing', 0)}  "
            f"Promoted: {research.get('promoted', 0)}", "",
            f"IMPORTANT  {'No critical issues.' if critical_count == 0 else str(critical_count)+' critical issue(s) — see alerts.'}",
            f"YOU NEED TO DO  {'Nothing.' if critical_count == 0 else 'Review the critical alert(s).'}",
        ])

    # ── read-only commands ───────────────────────────────────────────────────
    def cmd_status(self, *, system_health: str, lifecycle_state: str,
                   capital: str, research_running: bool, paper_running: bool,
                   is_live: bool, warnings: int, critical: int) -> str:
        return "\n".join([
            "SIGBOT STATUS", "",
            f"System: {system_health}", f"State: {lifecycle_state}",
            f"Capital: {capital}",
            f"Research: {'RUNNING' if research_running else 'STOPPED'}",
            f"Paper: {'RUNNING' if paper_running else 'STOPPED'}",
            f"Live: {'YES' if is_live else 'NO'}",
            f"Warnings: {warnings}", f"Critical: {critical}"])

    def cmd_evidence(self, *, has_backtest: bool, has_oos: bool,
                     has_provisional: bool, has_paper: bool, has_live: bool,
                     capital: str) -> str:
        line = lambda b, yes="Available", no="None": yes if b else no
        return "\n".join([
            "PUBLIC EVIDENCE", "",
            f"Historical: {line(has_backtest)}",
            f"OOS: {line(has_oos)}",
            f"Provisional: {line(has_provisional, 'Some figures')}",
            f"Paper: {line(has_paper, 'Available', 'No qualifying figures yet')}",
            f"Live: {line(has_live)}", "", f"Capital: {capital}"])

    def render_live_activation(self, *, model: str, activated_at: str,
                               capital: str) -> str:
        """The first LIVE message — makes the zero-state explicit. Live figures
        come from the lifecycle's zeroed record; history is never included."""
        return "\n".join([
            "🔓 LIVE ACTIVATED", "", f"Model: {model}",
            f"Activated: {activated_at}", "",
            "Live record:", "0 days", "0 trades", "$0 P&L", "",
            "Historical results are NOT included in the live record.",
            f"Capital: {capital}"])


def describe() -> str:
    return "\n".join([
        "TELEGRAM OPS — plain-English awareness, consumes canonical state",
        "",
        "  Four classes: CRITICAL (immediate), IMPORTANT (state change), DAILY",
        "  summary, WEEKLY research digest. No spam — signals/hypotheses/",
        "  heartbeats live on the site, not here.",
        "",
        "  STRUCTURAL PROPERTIES:",
        "    1. Consumes, never calculates — no P&L/capital math here, so Website",
        "       and Telegram can't disagree.",
        "    2. Incident dedup + restart-safe — one failure = one alert via an",
        "       immutable id with OPEN->ACK->RECOVERED; restart restores state",
        "       and does not re-blast history.",
        "    3. Read-only — no /buy /sell /go_live /promote /enable_capital exist.",
        "    4. Zero-state aware — live figures come from the lifecycle's zeroed",
        "       record; historical numbers never mix in.",
    ])
