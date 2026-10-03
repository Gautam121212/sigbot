"""SIGBOT 24/7 Operating Loop + Command Center + Self-Diagnostic Recovery.

Ties together the fourteen shipped engines (production, research, assurance,
paper, shadow, health, intelligence, scenario, arena, distillation, innovation,
firewall, reconciliation, system_assurance) into one continuously-running system
across the five model families — while keeping production models structurally
isolated from experimental research.

THE CORE RULE, ENFORCED IN CODE (not convention):
  Research may be aggressive; promotion must be conservative; failure triggers
  diagnosis + quarantine; repair happens OUTSIDE production; a repaired model
  earns its way back through the same gates. A quarantined model cannot authorize
  capital, and a model only leaves quarantine when ALL mandatory recovery checks
  pass — never because returns improved or an operator says "it looks fine".

This module is deterministic. It does not predict or trade — it ORCHESTRATES,
DIAGNOSES, and GATES. No live retuning; no silent deletion; NO_TRADE and
SYSTEM_PAUSE are first-class outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .system_assurance import (
    ApprovedChampion, ExperimentLeakError, TradeAuthRequest,
    authorize_capital)

MODEL_FAMILIES = ("stocks", "ventures", "news", "crypto", "ideas")


# ── incident severity (item 5) ──────────────────────────────────────────────
class ModelState(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"
    SYSTEM_PAUSED = "system_paused"
    RECOVERY = "recovery"
    VERIFIED = "verified"
    ACTIVE = "active"


# critical categories that must quarantine or pause (item 5)
class CheckCategory(str, Enum):
    DATA_INTEGRITY = "data_integrity"          # critical
    MODEL_INTEGRITY = "model_integrity"        # critical
    VERSION_INTEGRITY = "version_integrity"    # critical
    PREDICTION_INTEGRITY = "prediction_integrity"  # critical
    RECONCILIATION = "reconciliation"          # critical
    CAPITAL_PATH = "capital_path"              # critical
    DATA_FRESHNESS = "data_freshness"          # degrade
    API_CONSISTENCY = "api_consistency"        # degrade
    WEBSITE_CONSISTENCY = "website_consistency"  # degrade
    EXECUTION_COST = "execution_cost"          # warn
    SCHEDULED_JOB = "scheduled_job"            # warn


CRITICAL_CATEGORIES = frozenset({
    CheckCategory.DATA_INTEGRITY, CheckCategory.MODEL_INTEGRITY,
    CheckCategory.VERSION_INTEGRITY, CheckCategory.PREDICTION_INTEGRITY,
    CheckCategory.RECONCILIATION, CheckCategory.CAPITAL_PATH,
})


@dataclass(frozen=True)
class DiagnosticCheck:
    category: CheckCategory
    name: str
    passed: bool
    detail: str = ""
    # which pipeline layer this check observes, for root-cause tracing
    layer: str = ""                    # data|model|prediction|db|api|website|risk


@dataclass(frozen=True)
class Incident:
    """Preserved forever (item 7). Records what broke, the evidence, and chain."""
    model: str
    timestamp: str
    failed_checks: tuple[DiagnosticCheck, ...]
    root_cause_layer: str
    resulting_state: ModelState
    evidence: str


# ── root-cause tracing (item 6): walk the dependency chain backward ─────────
# The pipeline order — a failure is attributed to the EARLIEST broken layer,
# because a later symptom is usually caused by an earlier break.
PIPELINE_LAYERS = ("data", "model", "prediction", "db", "api", "website", "risk")


def trace_root_cause(failed: list[DiagnosticCheck]) -> str:
    """Attribute the failure to the earliest broken layer, not the final symptom.
    data corrupted -> prediction abnormal -> website fine => blame DATA.
    db fine -> api fine -> website stale => blame WEBSITE/API, not the model."""
    broken_layers = {c.layer for c in failed if c.layer}
    for layer in PIPELINE_LAYERS:
        if layer in broken_layers:
            return layer
    return "unknown"


# ── the self-diagnostic engine (item 4) ─────────────────────────────────────
@dataclass
class SystemDiagnosticEngine:
    """Deterministic. Runs the full check battery for a model and classifies the
    resulting state. Critical-category failures force QUARANTINE; a systemic
    (capital-path or reconciliation) failure forces SYSTEM_PAUSED."""

    def classify(self, checks: list[DiagnosticCheck]) -> ModelState:
        failed = [c for c in checks if not c.passed]
        if not failed:
            return ModelState.HEALTHY
        failed_cats = {c.category for c in failed}
        # systemic: capital-path or reconciliation breach pauses the whole system
        if CheckCategory.CAPITAL_PATH in failed_cats or \
                CheckCategory.RECONCILIATION in failed_cats:
            return ModelState.SYSTEM_PAUSED
        # any other critical category quarantines the model
        if failed_cats & CRITICAL_CATEGORIES:
            return ModelState.QUARANTINED
        # degrade-level categories
        if len(failed) >= 2:
            return ModelState.DEGRADED
        return ModelState.WARNING

    def diagnose(self, model: str, checks: list[DiagnosticCheck],
                 now: datetime | None = None) -> Incident | None:
        failed = [c for c in checks if not c.passed]
        if not failed:
            return None
        state = self.classify(checks)
        root = trace_root_cause(failed)
        ts = (now or datetime.now(timezone.utc)).isoformat()
        return Incident(
            model=model, timestamp=ts, failed_checks=tuple(failed),
            root_cause_layer=root, resulting_state=state,
            evidence=f"{len(failed)} failed check(s); root cause: {root} layer")


# ── operational readiness policy (item 13) ──────────────────────────────────
# The mandatory checks a model must pass to be allowed to authorize capital.
RECOVERY_CHECKS = (
    "data_integrity", "point_in_time", "prediction_generation", "persistence",
    "api", "website_display", "model_version_lock", "research_isolation",
    "firewall", "reconciliation", "health_monitor", "end_to_end_canary",
)


@dataclass(frozen=True)
class OperationalReadinessPolicy:
    """Versioned. Defines the exact mandatory checks. 'Perfect' is not the
    absence of all possible errors — it is these required checks passing."""
    version: str = "orp-v1"
    mandatory: tuple[str, ...] = RECOVERY_CHECKS

    def ready(self, passed_checks: set[str]) -> bool:
        return all(c in passed_checks for c in self.mandatory)

    def missing(self, passed_checks: set[str]) -> list[str]:
        return [c for c in self.mandatory if c not in passed_checks]


# ── the per-model lifecycle + quarantine/recovery state machine ─────────────
@dataclass
class ModelLifecycle:
    """One model family's state. A quarantined model cannot be resumed except by
    passing every mandatory recovery check (item 9)."""
    family: str
    state: ModelState = ModelState.ACTIVE
    champion: ApprovedChampion | None = None
    incidents: list[Incident] = field(default_factory=list)
    policy: OperationalReadinessPolicy = field(
        default_factory=OperationalReadinessPolicy)

    def record_incident(self, inc: Incident) -> None:
        self.incidents.append(inc)
        # quarantine/pause is sticky — a model cannot trade from these states
        if inc.resulting_state in (ModelState.QUARANTINED,
                                   ModelState.SYSTEM_PAUSED):
            self.state = inc.resulting_state

    def can_authorize_capital(self) -> bool:
        return self.state == ModelState.ACTIVE

    def attempt_recovery(self, passed_checks: set[str]) -> ModelState:
        """QUARANTINED -> RECOVERY -> VERIFIED -> ACTIVE, but ONLY if every
        mandatory check passes. Returns stays QUARANTINED otherwise. Never
        resumes on 'returns improved' or operator say-so."""
        if self.state not in (ModelState.QUARANTINED, ModelState.SYSTEM_PAUSED,
                              ModelState.RECOVERY):
            return self.state
        if not self.policy.ready(passed_checks):
            self.state = ModelState.RECOVERY   # in recovery but not cleared
            return self.state
        self.state = ModelState.ACTIVE
        return self.state


# ── capital authorization through the lifecycle (item 3) ────────────────────
def authorize_through_lifecycle(request: TradeAuthRequest,
                                lifecycle: ModelLifecycle) -> bool:
    """The single path to capital. Checks the model is ACTIVE (not quarantined/
    paused/recovery) AND is the approved champion. A quarantined or experimental
    model attempting this raises — a visible containment incident."""
    if not lifecycle.can_authorize_capital():
        raise ExperimentLeakError(
            f"{lifecycle.family} model attempted capital authorization while "
            f"state={lifecycle.state.value} — only ACTIVE models may trade")
    if lifecycle.champion is None:
        raise ExperimentLeakError(
            f"{lifecycle.family} has no approved champion — cannot authorize")
    return authorize_capital(request, lifecycle.champion)


# ── experienced-trader decision architecture (item 11) ──────────────────────
class TradeDecision(str, Enum):
    TRADE = "trade"
    SMALL_TRADE = "small_trade"
    WAIT = "wait"
    NO_TRADE = "no_trade"
    PAUSE = "pause"


@dataclass(frozen=True)
class DecisionInputs:
    expected_edge: float
    historical_confidence: float       # 0-1
    downside: float                    # expected adverse move, positive number
    liquidity_ok: bool
    portfolio_correlation: float       # with existing book
    existing_exposure_pct: float
    model_state: ModelState


def decide(inp: DecisionInputs) -> TradeDecision:
    """Calculated risk, not max-predicted-return. NO_TRADE is first-class."""
    if inp.model_state in (ModelState.QUARANTINED, ModelState.SYSTEM_PAUSED,
                           ModelState.RECOVERY):
        return TradeDecision.PAUSE
    if not inp.liquidity_ok:
        return TradeDecision.NO_TRADE
    if inp.expected_edge <= 0:
        return TradeDecision.NO_TRADE
    # edge vs downside — insufficient reward for risk
    if inp.expected_edge < 0.3 * inp.downside:
        return TradeDecision.WAIT
    # crowded or already over-exposed -> smaller or wait
    if inp.existing_exposure_pct > 0.25 or inp.portfolio_correlation > 0.7:
        return TradeDecision.SMALL_TRADE
    if inp.historical_confidence < 0.5:
        return TradeDecision.SMALL_TRADE
    return TradeDecision.TRADE


# ── the command center (item 12) ────────────────────────────────────────────
@dataclass(frozen=True)
class ModelStatus:
    family: str
    production_version: str
    research_generation: str
    state: ModelState
    data_fresh: bool
    last_cycle_ok: bool
    open_incidents: int
    can_trade: bool


@dataclass
class CommandCenter:
    """System-wide view. 'Safe to operate' is True only if no model is paused and
    no model is in a critical-failure state."""
    lifecycles: dict[str, ModelLifecycle] = field(default_factory=dict)

    def register(self, lifecycle: ModelLifecycle) -> None:
        self.lifecycles[lifecycle.family] = lifecycle

    def model_status(self, family: str, data_fresh: bool,
                     last_cycle_ok: bool) -> ModelStatus:
        lc = self.lifecycles[family]
        champ = lc.champion
        return ModelStatus(
            family=family,
            production_version=champ.version if champ else "none",
            research_generation=champ.research_generation if champ else "none",
            state=lc.state, data_fresh=data_fresh, last_cycle_ok=last_cycle_ok,
            open_incidents=len(lc.incidents),
            can_trade=lc.can_authorize_capital())

    def system_safe_to_operate(self) -> bool:
        """False if ANY model is SYSTEM_PAUSED (a systemic failure stops
        everything), or if the whole system has no active models."""
        states = [lc.state for lc in self.lifecycles.values()]
        if any(s == ModelState.SYSTEM_PAUSED for s in states):
            return False
        return any(s == ModelState.ACTIVE for s in states)

    def paused_models(self) -> list[str]:
        return [f for f, lc in self.lifecycles.items()
                if not lc.can_authorize_capital()]


# ── cycle verification (item 1): every expected cycle must have occurred ─────
@dataclass
class CycleTracker:
    """Verifies that every expected scheduled cycle actually ran. A missing cycle
    is a scheduled-job failure, not silently tolerated."""
    expected: dict[str, int] = field(default_factory=dict)   # family -> count
    completed: dict[str, int] = field(default_factory=dict)

    def expect(self, family: str, n: int) -> None:
        self.expected[family] = n

    def complete(self, family: str) -> None:
        self.completed[family] = self.completed.get(family, 0) + 1

    def missing_cycles(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f, exp in self.expected.items():
            done = self.completed.get(f, 0)
            if done < exp:
                out[f] = exp - done
        return out

    def all_cycles_ran(self) -> bool:
        return not self.missing_cycles()


def describe() -> str:
    return "\n".join([
        "SIGBOT 24/7 OPERATING LOOP + COMMAND CENTER + SELF-DIAGNOSTIC RECOVERY",
        "",
        "  Orchestrates the 14 engines across 5 model families continuously, with",
        "  production structurally isolated from research. Deterministic: it",
        "  orchestrates, diagnoses and gates — it does not predict or trade.",
        "",
        "  CORE RULE ENFORCED IN CODE: research aggressive, promotion conservative,",
        "  failure quarantines, repair outside production, recovery through the",
        "  same gates. A quarantined model CANNOT authorize capital; it leaves",
        "  quarantine only when ALL mandatory recovery checks pass — never on",
        "  'returns improved' or operator say-so.",
        "",
        "  SELF-DIAGNOSTIC: critical failures (data/model/version/prediction",
        "  integrity, reconciliation, capital-path) force QUARANTINED or",
        "  SYSTEM_PAUSED. Root-cause tracing attributes a failure to the EARLIEST",
        "  broken layer, not the final symptom (stale website -> blame api/website,",
        "  not the model). NO_TRADE and SYSTEM_PAUSE are first-class outcomes.",
    ])
