"""Live lifecycle state machine — SIGBOT earns every state; it never defaults to LIVE.

Enforces the release philosophy in code: "SIGBOT starts at zero for live
performance. It earns every public state progressively. It never goes LIVE merely
because the code works." The lifecycle is the authoritative system-state source
that the website, dashboard and Telegram all consume — none of them invents state.

THREE PROPERTIES MADE STRUCTURAL (the places this goes wrong in practice):

  1. TWO INDEPENDENT GATES TO LIVE. Automated eligibility (every gate PASS) can
     only produce LIVE_CANDIDATE — never LIVE. Crossing to LIVE requires a
     separate explicit human activation of a specific champion version. The
     research brain can say "eligible"; it can never say "trading".

  2. ZERO-STATE LIVE RECORD. Live counters begin at zero on the activation
     timestamp. Historical (backtest/oos) and paper records are SEPARATE
     histories that are never merged in. A 17% historical CAGR can never become a
     "17% live CAGR" — the live record structurally starts empty.

  3. FAIL-TO-SAFE. Any critical failure sends the system to QUARANTINED or
     TRADING_PAUSED from ANY state including LIVE, and capital blocks. Recovery
     requires re-passing the gates, not an operator override.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleState(str, Enum):
    BUILDING = "building"
    HISTORICAL_VALIDATION = "historical_validation"
    OOS_VALIDATION = "oos_validation"
    PAPER_VALIDATION = "paper_validation"
    LIVE_CANDIDATE = "live_candidate"       # automated gates passed — NOT live
    LIVE = "live"                            # only after explicit human activation
    # failure states, reachable from anywhere
    QUARANTINED = "quarantined"
    TRADING_PAUSED = "trading_paused"


# the forward progression (failure states are separate, reachable from any state)
_FORWARD = [
    LifecycleState.BUILDING,
    LifecycleState.HISTORICAL_VALIDATION,
    LifecycleState.OOS_VALIDATION,
    LifecycleState.PAPER_VALIDATION,
    LifecycleState.LIVE_CANDIDATE,
    LifecycleState.LIVE,
]


# the mandatory gates for live readiness (blueprint item 20)
LIVE_READINESS_GATES = (
    "historical_validation", "variable_audit", "lookahead_audit",
    "oos_validation", "multiple_testing_review", "matched_control",
    "robustness", "stress_test", "realistic_cost_model", "liquidity_test",
    "risk_firewall", "paper_pipeline", "reconciliation", "health_monitor",
    "restart_recovery", "api_db_consistency", "marketing_evidence_consistency",
    "telegram_monitoring",
)


class IllegalTransition(Exception):
    """Raised on any transition the lifecycle forbids — e.g. jumping to LIVE
    without human activation, or skipping a validation stage."""


@dataclass(frozen=True)
class LiveRecord:
    """The live performance record. ALWAYS starts at zero on activation. Never
    seeded from historical or paper numbers."""
    activated_at: str | None = None
    days: int = 0
    trades: int = 0
    pnl: float = 0.0
    drawdown_pct: float = 0.0

    @staticmethod
    def zero(activated_at: str) -> "LiveRecord":
        return LiveRecord(activated_at=activated_at, days=0, trades=0,
                          pnl=0.0, drawdown_pct=0.0)


@dataclass
class LiveLifecycle:
    """The authoritative state machine. Advances only through the defined
    progression; reaches LIVE only via explicit human activation; starts the live
    record at zero; and fails to safe from any state."""
    champion_version: str
    state: LifecycleState = LifecycleState.BUILDING
    gates_passed: set[str] = field(default_factory=set)
    human_activated_version: str | None = None
    live_record: LiveRecord | None = None

    # ── forward progression through validation stages ────────────────────────
    def advance(self, to: LifecycleState) -> LifecycleState:
        """Advance one forward stage at a time, up to LIVE_CANDIDATE. Cannot skip
        stages, cannot reach LIVE here (that needs activation)."""
        if to == LifecycleState.LIVE:
            raise IllegalTransition(
                "LIVE is reached only via activate_live() with human approval — "
                "never through advance()")
        if to not in _FORWARD:
            raise IllegalTransition(f"{to.value} is not a forward stage")
        if self.state not in _FORWARD:
            raise IllegalTransition(
                f"cannot advance from failure state {self.state.value} — recover first")
        cur_i = _FORWARD.index(self.state)
        to_i = _FORWARD.index(to)
        if to_i != cur_i + 1:
            raise IllegalTransition(
                f"cannot jump {self.state.value} -> {to.value}; advance one stage")
        # entering LIVE_CANDIDATE requires all automated gates passed
        if to == LifecycleState.LIVE_CANDIDATE and not self.all_gates_passed():
            raise IllegalTransition(
                "cannot become LIVE_CANDIDATE until every readiness gate passes: "
                f"missing {sorted(set(LIVE_READINESS_GATES) - self.gates_passed)}")
        self.state = to
        return self.state

    def pass_gate(self, gate: str) -> None:
        if gate not in LIVE_READINESS_GATES:
            raise ValueError(f"unknown gate '{gate}'")
        self.gates_passed.add(gate)

    def all_gates_passed(self) -> bool:
        return set(LIVE_READINESS_GATES).issubset(self.gates_passed)

    def missing_gates(self) -> list[str]:
        return sorted(set(LIVE_READINESS_GATES) - self.gates_passed)

    # ── the second, human gate ───────────────────────────────────────────────
    def activate_live(self, version: str, activated_at: str,
                      human_approved: bool) -> LifecycleState:
        """Gate B — explicit human activation. The ONLY path to LIVE. Requires:
        the system is a LIVE_CANDIDATE, the version matches the vetted champion,
        and a human explicitly approved THIS version. Starts the live record at
        zero."""
        if self.state != LifecycleState.LIVE_CANDIDATE:
            raise IllegalTransition(
                f"can only activate LIVE from LIVE_CANDIDATE, not {self.state.value}")
        if not human_approved:
            raise IllegalTransition(
                "LIVE requires explicit human approval — automated eligibility "
                "is not sufficient")
        if version != self.champion_version:
            raise IllegalTransition(
                f"activation version {version} != vetted champion "
                f"{self.champion_version} — refusing to activate an unvetted model")
        self.human_activated_version = version
        self.state = LifecycleState.LIVE
        self.live_record = LiveRecord.zero(activated_at)   # ZERO, always
        return self.state

    # ── fail-to-safe from any state ──────────────────────────────────────────
    def quarantine(self, reason: str) -> LifecycleState:
        self.state = LifecycleState.QUARANTINED
        return self.state

    def pause_trading(self, reason: str) -> LifecycleState:
        self.state = LifecycleState.TRADING_PAUSED
        return self.state

    # ── capital authorization ────────────────────────────────────────────────
    def capital_authorized(self) -> bool:
        """Capital flows ONLY in LIVE with a human-activated matching version.
        Every other state — including LIVE_CANDIDATE — blocks capital."""
        return (self.state == LifecycleState.LIVE
                and self.human_activated_version == self.champion_version)

    def capital_label(self) -> str:
        return "AUTHORIZED" if self.capital_authorized() else "LOCKED"

    # ── the record the website/telegram render (never merges histories) ──────
    def public_state(self) -> dict[str, object]:
        lr = self.live_record
        return {
            "system_state": self.state.value.upper(),
            "capital": self.capital_label(),
            "champion": self.champion_version,
            "live_days": lr.days if lr else 0,
            "live_trades": lr.trades if lr else 0,
            "live_pnl": lr.pnl if lr else 0.0,
            "live_drawdown_pct": lr.drawdown_pct if lr else 0.0,
            "has_live_record": lr is not None,
        }


def build_live_readiness_report(lc: LiveLifecycle) -> str:
    """The immutable go-live report (blueprint item 20). Shows every gate's
    status and the resulting eligibility. STATUS is LIVE_CANDIDATE at most — the
    report never says LIVE, because only human activation does that."""
    lines = ["LIVE READINESS REPORT", "=" * 30,
             f"  champion version: {lc.champion_version}", ""]
    for gate in LIVE_READINESS_GATES:
        mark = "PASS" if gate in lc.gates_passed else "— not yet"
        lines.append(f"  {gate:34} {mark}")
    lines.append("")
    lines.append(f"  CAPITAL   {lc.capital_label()}")
    eligible = lc.all_gates_passed()
    lines.append(f"  STATUS    {'LIVE CANDIDATE (awaiting human activation)' if eligible else 'NOT YET ELIGIBLE'}")
    return "\n".join(lines)


def describe() -> str:
    return "\n".join([
        "LIVE LIFECYCLE — SIGBOT earns every state; it never defaults to LIVE",
        "",
        "  BUILDING -> HISTORICAL -> OOS -> PAPER -> LIVE_CANDIDATE -> (human) -> LIVE",
        "",
        "  THREE STRUCTURAL PROPERTIES:",
        "    1. Two gates to live — automated eligibility reaches only",
        "       LIVE_CANDIDATE; LIVE needs a separate explicit human activation",
        "       of the exact vetted champion version. advance() literally cannot",
        "       produce LIVE.",
        "    2. Zero-state live record — live counters start at 0 on activation;",
        "       historical and paper records are never merged in. A 17% backtest",
        "       CAGR can never become a 17% live CAGR.",
        "    3. Fail-to-safe — any critical failure -> QUARANTINED/TRADING_PAUSED",
        "       from any state including LIVE, and capital blocks.",
        "",
        "  Capital is AUTHORIZED only in LIVE with a human-activated matching",
        "  version — every other state, LIVE_CANDIDATE included, is LOCKED. This",
        "  is the authoritative state the website, dashboard and Telegram consume.",
    ])
