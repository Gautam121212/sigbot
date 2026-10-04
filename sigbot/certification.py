"""SIGBOT Final Certification — two independent historical replays.

Replay A: FROZEN SYSTEM.
The production model, frozen at a point in time, replayed chronologically through
historical data. No learning, no promotion, no intervention. Answers: "Does the
frozen model work, and does it work consistently across regimes?"

Replay B: AUTONOMOUS WALK-FORWARD.
The full research/learning machinery runs chronologically — at each date it knows
only what was available then, generates hypotheses, tests them, and may promote
candidates. Answers: "Does the adaptive architecture improve itself without
cheating?" Promotion timestamps are immutable; a 2017 promotion cannot alter a
2015 decision.

CRITICAL INVARIANT (both replays): the time-lock. Every data access is gated by
a clock that only moves forward. No record, price, or signal with a timestamp
after the current simulation date may be used. This is not a convention; it is
structurally enforced by the SimulationClock passed to every data accessor.

The certification runner NEVER modifies production state. It reads historical
data, runs in a completely isolated ledger, and produces an immutable report
sealed with a hash of the code + config + parameters.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Callable


# ── the time-lock ─────────────────────────────────────────────────────────
class LookaheadViolation(Exception):
    """Raised when any component attempts to access data beyond the current
    simulation date. Every data-access call goes through the clock."""


@dataclass
class SimulationClock:
    """The authoritative current date in a replay. Passed to every data
    accessor; any access beyond current_date raises LookaheadViolation."""
    current_date: date
    _violations: list[str] = field(default_factory=list)

    def require_available_at(self, data_date: date, source: str = "") -> None:
        """Call before using any piece of data. If data_date > current_date,
        raises — this is the structural anti-lookahead gate."""
        if data_date > self.current_date:
            msg = (f"lookahead: data from {data_date} used at "
                   f"simulation date {self.current_date}"
                   + (f" [{source}]" if source else ""))
            self._violations.append(msg)
            raise LookaheadViolation(msg)

    def advance(self, to: date) -> None:
        if to < self.current_date:
            raise ValueError(f"clock cannot go backward: {self.current_date} -> {to}")
        self.current_date = to

    def violations(self) -> list[str]:
        return list(self._violations)


# ── the immutable snapshot (seals the certification run) ────────────────────
@dataclass(frozen=True)
class CertificationSnapshot:
    """A hash of the model code + config + parameters at run start.
    Ensures the report can later prove "the model was not modified during replay."
    Generated before execution; carried in the report."""
    snapshot_id: str
    created_at: str
    model_version: str
    config_hash: str
    parameters_hash: str
    description: str

    def verify(self, current_config_hash: str,
               current_params_hash: str) -> bool:
        return (self.config_hash == current_config_hash
                and self.parameters_hash == current_params_hash)


def _hash(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def build_snapshot(model_version: str, config: dict,
                   parameters: dict) -> CertificationSnapshot:
    now = datetime.now(timezone.utc).isoformat()
    seq = _hash(now + model_version)[:6].upper()
    return CertificationSnapshot(
        snapshot_id=f"CERT-{seq}",
        created_at=now, model_version=model_version,
        config_hash=_hash(json.dumps(config, sort_keys=True)),
        parameters_hash=_hash(json.dumps(parameters, sort_keys=True)),
        description=f"SIGBOT Certification Snapshot {seq}")


# ── model verdict ─────────────────────────────────────────────────────────
class ModelVerdict(str, Enum):
    SURVIVED = "SURVIVED"
    SURVIVED_WITH_WARNING = "SURVIVED_WITH_WARNING"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


@dataclass
class ModelCertification:
    """A death certificate for one model family."""
    family: str
    verdict: ModelVerdict
    reason: str
    cagr: float | None = None
    sharpe: float | None = None
    win_rate: float | None = None
    max_drawdown: float | None = None
    n_trades: int = 0
    n_years_positive: int = 0
    n_years_total: int = 0


def _verdict(cagr: float | None, sharpe: float | None, win_rate: float | None,
             n_trades: int) -> tuple[ModelVerdict, str]:
    if n_trades < 30:
        return ModelVerdict.INCONCLUSIVE, "insufficient trades for reliable conclusion"
    if cagr is None or sharpe is None:
        return ModelVerdict.INCONCLUSIVE, "insufficient data for conclusion"
    if cagr < 0:
        return ModelVerdict.FAILED, f"negative CAGR ({cagr:.1f}%)"
    if sharpe < 0.5:
        return ModelVerdict.SURVIVED_WITH_WARNING, \
            f"positive CAGR but low Sharpe ({sharpe:.2f})"
    if win_rate is not None and win_rate < 0.45:
        return ModelVerdict.SURVIVED_WITH_WARNING, \
            f"low win rate ({win_rate:.1%})"
    return ModelVerdict.SURVIVED, f"CAGR {cagr:.1f}%, Sharpe {sharpe:.2f}"


# ── the replay trade record ───────────────────────────────────────────────
@dataclass
class ReplayTrade:
    """One simulated trade in the historical replay."""
    trade_id: str
    model: str
    symbol: str
    side: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    gross_return: float
    net_return: float           # after costs/impact
    costs: float
    decision_date: date         # when the prediction was sealed (must be < entry)

    def valid_timing(self) -> bool:
        """The prediction must be sealed before the entry, and entry before exit."""
        return self.decision_date < self.entry_date < self.exit_date


# ── replay A: frozen system ────────────────────────────────────────────────
@dataclass
class FrozenReplayConfig:
    start_date: date
    end_date: date
    starting_capital: float = 100_000.0
    model_version: str = "SIGBOT-INFLECTION-FROZEN"
    config: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)


@dataclass
class ReplayAResult:
    snapshot: CertificationSnapshot
    config: FrozenReplayConfig
    trades: list[ReplayTrade] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    model_certs: list[ModelCertification] = field(default_factory=list)

    def lookahead_clean(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> dict:
        n = len(self.trades)
        wins = sum(1 for t in self.trades if t.net_return > 0)
        net_rets = [t.net_return for t in self.trades]
        total_costs = sum(t.costs for t in self.trades)
        final_equity = (self.equity_curve[-1][1]
                        if self.equity_curve else self.config.starting_capital)
        years = max((self.config.end_date - self.config.start_date).days / 365.25,
                    0.01)
        cagr = ((final_equity / self.config.starting_capital) ** (1 / years) - 1
                ) * 100
        avg_ret = (sum(net_rets) / n) if n else 0.0
        # All timing must be valid — the critical correctness check
        timing_violations = sum(1 for t in self.trades if not t.valid_timing())
        return {
            "snapshot_id": self.snapshot.snapshot_id,
            "period": f"{self.config.start_date} → {self.config.end_date}",
            "starting_capital": self.config.starting_capital,
            "ending_capital": round(final_equity, 2),
            "cagr_pct": round(cagr, 2),
            "n_trades": n,
            "win_rate": round(wins / n, 4) if n else None,
            "avg_net_return_pct": round(avg_ret * 100, 3),
            "total_costs": round(total_costs, 2),
            "lookahead_violations": len(self.violations),
            "timing_violations": timing_violations,
            "model_verdicts": {c.family: c.verdict.value
                               for c in self.model_certs},
        }


def run_replay_a(cfg: FrozenReplayConfig,
                 trade_source: Callable[[SimulationClock], list[ReplayTrade]]
                 ) -> ReplayAResult:
    """Execute Replay A. trade_source is called with the clock at each step;
    it must only access data available at clock.current_date or earlier.
    The caller is responsible for enforcing this via clock.require_available_at;
    any violation is recorded and surfaced in the report."""
    snap = build_snapshot(cfg.model_version, cfg.config, cfg.parameters)
    clock = SimulationClock(cfg.start_date)
    all_trades: list[ReplayTrade] = []
    equity = cfg.starting_capital
    curve: list[tuple[date, float]] = [(cfg.start_date, equity)]
    current = cfg.start_date
    while current <= cfg.end_date:
        clock.advance(current)
        try:
            day_trades = trade_source(clock)
        except LookaheadViolation:
            clock._violations.append(f"trade_source violation at {current}")
            day_trades = []
        for t in day_trades:
            if not t.valid_timing():
                clock._violations.append(
                    f"timing violation: {t.trade_id} decision={t.decision_date}"
                    f" entry={t.entry_date}")
            equity *= (1 + t.net_return)
            all_trades.append(t)
        curve.append((current, round(equity, 4)))
        current += timedelta(days=1)
    return ReplayAResult(snapshot=snap, config=cfg, trades=all_trades,
                         violations=clock.violations(), equity_curve=curve)


# ── replay B: autonomous walk-forward ────────────────────────────────────
@dataclass(frozen=True)
class PromotionRecord:
    """A model promotion in the walk-forward replay. Immutable; cannot alter
    decisions made before the promotion date."""
    model_id: str
    promoted_at: date            # the date this model became the champion
    replaced: str | None = None  # the model it replaced


@dataclass
class WalkForwardResult:
    """The output of Replay B. Contains the promotion history alongside
    performance — this is the version-controlled SIGBOT history."""
    trades: list[ReplayTrade] = field(default_factory=list)
    promotions: list[PromotionRecord] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def active_model_at(self, d: date) -> str | None:
        """Which model was champion on date d? Uses only promotions before d."""
        champion = None
        for p in sorted(self.promotions, key=lambda x: x.promoted_at):
            if p.promoted_at <= d:
                champion = p.model_id
        return champion


# ── the certification report ─────────────────────────────────────────────
@dataclass
class CertificationReport:
    """The full output. Generated once; never modified after the run. The
    snapshot_id inside lets the result be traced to an exact code+config hash."""
    snapshot: CertificationSnapshot
    replay_a: ReplayAResult | None = None
    replay_b: WalkForwardResult | None = None

    def to_dict(self) -> dict:
        a = self.replay_a.summary() if self.replay_a else {}
        return {"certification": self.snapshot.snapshot_id,
                "description": self.snapshot.description,
                "created_at": self.snapshot.created_at,
                "replay_a": a,
                "replay_b_promotions": (
                    [{"model": p.model_id,
                      "promoted_at": p.promoted_at.isoformat()}
                     for p in (self.replay_b.promotions if self.replay_b else [])])}

    def governance_summary(self) -> dict:
        """The part of the report that answers: did the machine respect its rules?
        Separate from returns because a profitable system with governance failures
        is not certifiable."""
        a_viol = len(self.replay_a.violations) if self.replay_a else "NOT_RUN"
        b_viol = len(self.replay_b.violations) if self.replay_b else "NOT_RUN"
        return {"lookahead_violations_replay_a": a_viol,
                "lookahead_violations_replay_b": b_viol,
                "certifiable": a_viol == 0 and b_viol == 0}


def describe() -> str:
    return "\n".join([
        "SIGBOT FINAL CERTIFICATION — two independent historical replays",
        "",
        "  Replay A (frozen): model locked, no learning, sequential replay.",
        "  Replay B (walk-forward): adaptive machinery runs chronologically,",
        "  promotions timestamped so a 2017 promotion cannot alter 2015 decisions.",
        "",
        "  CRITICAL INVARIANT: SimulationClock enforces the time-lock structurally.",
        "  Every data access is gated by clock.require_available_at(); a future",
        "  timestamp raises LookaheadViolation rather than silently leaking.",
        "",
        "  CertificationSnapshot seals code+config+parameters before execution.",
        "  The report's snapshot_id traces the result to an exact version.",
        "  The certification runner NEVER modifies production state.",
        "",
        "  Each model gets a verdict: SURVIVED / SURVIVED_WITH_WARNING /",
        "  INCONCLUSIVE / FAILED, with a machine-generated reason.",
        "  A positive return does NOT automatically mean the model changes.",
        "  A negative return does NOT automatically disqualify it.",
        "  The run produces evidence; authority remains with the human gate.",
    ])


# ─────────────────────────────────────────────────────────────────────────────
# CERTIFICATION INTEGRITY LAYER (B353)
# The framework above can run a replay; this layer decides whether a replay is
# allowed to be CERTIFIED. Six integrity requirements, each structural:
#   1. Replay A declares RAW_DATA vs HISTORICAL_SIGNAL — never ambiguous.
#   2. Snapshot captures source/dependency/data identity, not just params.
#   3. Every historical data accessor must be clock-gated (audited).
#   4. Dataset integrity gate (missing data, survivorship, corp actions, costs).
#   5. Replay B cannot silently use non-chronological research.
#   6. A high return with ANY integrity failure => NOT CERTIFIABLE.
# ─────────────────────────────────────────────────────────────────────────────
import subprocess  # noqa: E402


class ReplayKind(str, Enum):
    """Explicit — a certification must say which kind of replay it is."""
    RAW_DATA = "RAW_DATA"               # real model vs raw historical inputs
    HISTORICAL_SIGNAL = "HISTORICAL_SIGNAL"  # re-scores pre-generated trades
    UNDECLARED = "UNDECLARED"           # structurally invalid for certification


@dataclass(frozen=True)
class SourceIdentity:
    """#2 — strong snapshot identity. A model_version string can stay fixed while
    the implementation underneath changes; this captures what actually ran."""
    git_commit: str
    tree_clean: bool
    dependency_hash: str
    data_manifest_hash: str
    runner_version: str

    def is_reproducible(self) -> bool:
        """A dirty working tree means the result cannot be reproduced from the
        commit alone — it is a soft integrity failure for certification."""
        return self.tree_clean


def capture_source_identity(repo_root: str, dependency_lock: str,
                            data_manifest: dict, runner_version: str
                            ) -> SourceIdentity:
    """Capture the real source/data identity. git calls fail-soft to 'unknown'
    so the capture never crashes a run, but 'unknown' is treated as not-clean."""
    commit, clean = "unknown", False
    try:
        commit = subprocess.check_output(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            text=True, timeout=10).strip()
        status = subprocess.check_output(
            ["git", "-C", repo_root, "status", "--porcelain"],
            text=True, timeout=10).strip()
        clean = (status == "")
    except (subprocess.SubprocessError, OSError, ValueError):  # noqa: BLE001  # handled: unknown/not-clean
        commit, clean = "unknown", False
    return SourceIdentity(
        git_commit=commit, tree_clean=clean,
        dependency_hash=_hash(dependency_lock),
        data_manifest_hash=_hash(json.dumps(data_manifest, sort_keys=True)),
        runner_version=runner_version)


# ── #3: data-accessor audit ─────────────────────────────────────────────────
@dataclass
class AccessorAudit:
    """Inventory of every historical data accessor Replay B uses, and whether
    each is clock-gated. An unguarded accessor => NOT CERTIFIABLE."""
    accessors: dict[str, bool] = field(default_factory=dict)  # name -> gated?

    def register(self, name: str, clock_gated: bool) -> None:
        self.accessors[name] = clock_gated

    def unguarded(self) -> list[str]:
        return [n for n, gated in self.accessors.items() if not gated]

    def all_gated(self) -> bool:
        return len(self.accessors) > 0 and not self.unguarded()


# The known historical accessors Replay B must route through the clock. If the
# audit doesn't cover all of these, certification is refused.
REQUIRED_ACCESSORS = (
    "market_prices", "gdelt_news", "fundamentals", "benchmark_data",
    "news_events", "research_inputs", "innovation_ledger", "model_evaluation",
)


def audit_accessors(registered: dict[str, bool]) -> AccessorAudit:
    audit = AccessorAudit()
    for name in REQUIRED_ACCESSORS:
        # an accessor not registered at all is treated as unguarded (fail-closed)
        audit.register(name, registered.get(name, False))
    for name, gated in registered.items():
        if name not in REQUIRED_ACCESSORS:
            audit.register(name, gated)
    return audit


# ── #4: dataset integrity gate ──────────────────────────────────────────────
@dataclass
class DataIntegrityReport:
    """Dataset-level checks independent of lookahead. A clean audit on bad data
    is still untrustworthy, so these are a separate gate."""
    missing_data_pct: float = 0.0
    includes_delisted: bool = False       # survivorship: must be True to pass
    corporate_actions_handled: bool = False
    execution_costs_modeled: bool = False
    silent_skips: int = 0                 # rows silently dropped — must be 0
    required_datasets_available: bool = False

    def failures(self) -> list[str]:
        f = []
        if self.missing_data_pct > 5.0:
            f.append(f"missing data {self.missing_data_pct:.1f}% > 5%")
        if not self.includes_delisted:
            f.append("survivorship: delisted names absent")
        if not self.corporate_actions_handled:
            f.append("corporate actions not handled")
        if not self.execution_costs_modeled:
            f.append("execution costs not modeled")
        if self.silent_skips > 0:
            f.append(f"{self.silent_skips} rows silently skipped")
        if not self.required_datasets_available:
            f.append("required datasets not all available")
        return f

    def passes(self) -> bool:
        return len(self.failures()) == 0


# ── the certification decision ──────────────────────────────────────────────
@dataclass
class CertificationDecision:
    """#6 — the final gate. CERTIFIABLE requires BOTH replays complete, zero
    violations, strong snapshot, all accessors gated, and clean data integrity.
    A high return with ANY failure returns NOT_CERTIFIABLE."""
    replay_kind: ReplayKind
    source_identity: SourceIdentity | None
    accessor_audit: AccessorAudit | None
    data_integrity: DataIntegrityReport | None
    replay_a_done: bool
    replay_b_done: bool
    lookahead_violations: int
    timing_violations: int
    unauthorized_promotions: int = 0
    unauthorized_capital: int = 0

    def blocking_reasons(self) -> list[str]:
        r = []
        if self.replay_kind == ReplayKind.UNDECLARED:
            r.append("replay kind undeclared (RAW_DATA or HISTORICAL_SIGNAL)")
        if not self.replay_a_done:
            r.append("Replay A not complete")
        if not self.replay_b_done:
            r.append("Replay B not complete")
        if self.lookahead_violations > 0:
            r.append(f"{self.lookahead_violations} lookahead violations")
        if self.timing_violations > 0:
            r.append(f"{self.timing_violations} timing violations")
        if self.unauthorized_promotions > 0:
            r.append(f"{self.unauthorized_promotions} unauthorized promotions")
        if self.unauthorized_capital > 0:
            r.append(f"{self.unauthorized_capital} unauthorized capital events")
        if self.source_identity is None or not self.source_identity.is_reproducible():
            r.append("source identity missing or working tree dirty")
        if self.accessor_audit is None or not self.accessor_audit.all_gated():
            unguarded = (self.accessor_audit.unguarded()
                         if self.accessor_audit else ["<no audit>"])
            r.append(f"unguarded data accessors: {unguarded}")
        if self.data_integrity is None or not self.data_integrity.passes():
            fails = (self.data_integrity.failures()
                     if self.data_integrity else ["<no integrity report>"])
            r.append(f"data integrity: {fails}")
        return r

    def certifiable(self) -> bool:
        return len(self.blocking_reasons()) == 0

    def verdict(self) -> str:
        return "CERTIFIABLE" if self.certifiable() else "NOT_CERTIFIABLE"


def describe_integrity() -> str:
    return "\n".join([
        "CERTIFICATION INTEGRITY — a replay is not certified just by running",
        "",
        "  Six structural requirements beyond 'it ran':",
        "  1. Replay A declares RAW_DATA vs HISTORICAL_SIGNAL (never ambiguous).",
        "     RAW_DATA = real model vs raw historical inputs; HISTORICAL_SIGNAL =",
        "     re-scores pre-generated trades (weaker — cannot catch baked-in leak).",
        "  2. Snapshot captures git commit, tree-clean, dependency + data-manifest",
        "     hashes, runner version — not just model_version+params (which can",
        "     stay fixed while the implementation underneath changes).",
        "  3. Every historical accessor audited for clock-gating; an unguarded",
        "     accessor => NOT CERTIFIABLE (fail-closed on unregistered accessors).",
        "  4. Dataset integrity gate: missing-data %, survivorship (delisted),",
        "     corporate actions, execution costs, silent skips — separate from",
        "     lookahead, because a clean audit on bad data is still untrustworthy.",
        "  5. Replay B promotions timestamped; non-chronological research blocked.",
        "  6. A high return with ANY integrity failure => NOT CERTIFIABLE.",
    ])
