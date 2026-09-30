"""Strategy intelligence engine — repository -> reproduction -> gap -> experiment.

The capstone of the control plane. It takes an EXTERNAL strategy (a GitHub repo,
a paper) as a RESEARCH INPUT — never a code template — independently reconstructs
it, reproduces it under SIGBOT's own reality model, detects gaps as MEASURED
evidence, generates isolated single-fix experiments, and routes them through the
existing sealed improvement harness. Survivors are promoted with full ancestry;
everything else is rejected and retained.

It builds ONLY on already-shipped components — the adapter (intentions), reality
engine (honest P&L), validation battery, and improvement harness (sealed,
one-gap-at-a-time). It adds NO new alpha and NO broker connectivity.

THE AI BOUNDARY, ENFORCED BY TYPES (not by instruction):
  The AIAnalyst may only return Hypothesis objects. There is no code path by
  which an AIAnalyst return value becomes a P&L number, a gap MEASURED status, a
  harness verdict, or a capital authorization. The deterministic engine is the
  only thing that measures, decides and promotes. AI = analyst; engine = judge.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from .improvement_harness import (
    Change, Component, ExperimentConfig, ExperimentResult,
    ResearchLedger, SplitConfig, Verdict, run_experiment)
from .reality_engine import CostModel, RealityResult, SimTrade, simulate


# ── provenance: never represent an inference as a fact ──────────────────────
class Provenance(str, Enum):
    DOCUMENTED = "documented"        # stated in README/docs
    INFERRED = "inferred"            # derived from code behavior
    UNVERIFIABLE = "unverifiable"    # cannot yet be confirmed


@dataclass(frozen=True)
class SpecField:
    """One piece of the spec, tagged with how we know it. A field can NEVER be
    stored without its provenance — inference is never presented as fact."""
    value: str
    provenance: Provenance


@dataclass
class StrategySpec:
    """Machine-readable reconstruction of an external strategy. Every field
    carries provenance so documented / inferred / unverifiable never blur."""
    repo_id: str
    universe: SpecField
    timeframe: SpecField
    indicators: tuple[SpecField, ...] = ()
    entry_rules: tuple[SpecField, ...] = ()
    exit_rules: tuple[SpecField, ...] = ()
    position_sizing: SpecField = field(
        default_factory=lambda: SpecField("unknown", Provenance.UNVERIFIABLE))
    leverage: SpecField = field(
        default_factory=lambda: SpecField("unknown", Provenance.UNVERIFIABLE))
    rebalancing: SpecField = field(
        default_factory=lambda: SpecField("unknown", Provenance.UNVERIFIABLE))
    training_process: SpecField = field(
        default_factory=lambda: SpecField("unknown", Provenance.UNVERIFIABLE))
    validation_process: SpecField = field(
        default_factory=lambda: SpecField("unknown", Provenance.UNVERIFIABLE))
    execution_assumptions: tuple[SpecField, ...] = ()
    claimed_performance: str = ""    # STORED AS A STRING — never a usable number

    def documented_fields(self) -> list[SpecField]:
        return [f for f in self._all() if f.provenance == Provenance.DOCUMENTED]

    def inferred_fields(self) -> list[SpecField]:
        return [f for f in self._all() if f.provenance == Provenance.INFERRED]

    def unverifiable_fields(self) -> list[SpecField]:
        return [f for f in self._all() if f.provenance == Provenance.UNVERIFIABLE]

    def _all(self) -> list[SpecField]:
        out: list[SpecField] = [self.universe, self.timeframe,
                                self.position_sizing, self.leverage,
                                self.rebalancing, self.training_process,
                                self.validation_process]
        out += list(self.indicators) + list(self.entry_rules)
        out += list(self.exit_rules) + list(self.execution_assumptions)
        return out


# ── Phase 1: repository analyzer ────────────────────────────────────────────
class RepositoryAnalyzer:
    """Ingests a repository's DOCUMENTED behavior and implementation details and
    produces a StrategySpec. It does NOT copy code — it records behavior. The
    claimed_performance is captured as a string for the claim-vs-reality report
    and is structurally barred from entering accounting."""

    def build_spec(self, repo_id: str, docs: dict[str, str],
                   analyst: AIAnalyst | None = None) -> StrategySpec:
        """docs is the extracted material (readme, config, described rules). An
        optional AIAnalyst may add INFERRED/UNVERIFIABLE hypotheses — but only as
        provenance-tagged SpecFields, never as documented fact."""
        universe = SpecField(docs.get("universe", "unknown"),
                             Provenance.DOCUMENTED if "universe" in docs
                             else Provenance.UNVERIFIABLE)
        timeframe = SpecField(docs.get("timeframe", "unknown"),
                              Provenance.DOCUMENTED if "timeframe" in docs
                              else Provenance.UNVERIFIABLE)
        indicators = tuple(SpecField(i, Provenance.DOCUMENTED)
                           for i in docs.get("indicators", "").split(",") if i)
        spec = StrategySpec(
            repo_id=repo_id, universe=universe, timeframe=timeframe,
            indicators=indicators,
            claimed_performance=docs.get("claimed_performance", ""))
        # AI hypotheses enter ONLY as inferred/unverifiable fields — advisory.
        if analyst is not None:
            for h in analyst.propose_hidden_assumptions(docs):
                object.__setattr__(spec, "execution_assumptions",
                                   spec.execution_assumptions
                                   + (SpecField(h.text, Provenance.INFERRED),))
        return spec


# ── Phase 2: independent reproduction ───────────────────────────────────────
@dataclass(frozen=True)
class ClaimRealityReport:
    """The three numbers, and the measurable differences. The published claim is
    a STRING context only — SIGBOT's two numbers are computed independently."""
    published_claim: str
    sigbot_idealized_reproduction: float   # frictionless, SIGBOT-computed
    sigbot_realistic_result: float         # after all reality-engine costs
    idealized_minus_realistic: float

    def overstatement_note(self) -> str:
        return (f"published says '{self.published_claim}'; SIGBOT idealized "
                f"{self.sigbot_idealized_reproduction}% -> realistic "
                f"{self.sigbot_realistic_result}% "
                f"(friction cost {self.idealized_minus_realistic}%)")


class StrategyReproducer:
    """Converts a StrategySpec into SIGBOT-native intentions and runs them
    through the reality engine. The repo's reported P&L NEVER enters — the string
    claim is carried only for the report."""

    def reproduce(self, spec: StrategySpec, intended_trades: list[SimTrade],
                  cost_model: CostModel | None = None) -> ClaimRealityReport:
        result: RealityResult = simulate(intended_trades, cost_model)
        return ClaimRealityReport(
            published_claim=spec.claimed_performance or "(none stated)",
            sigbot_idealized_reproduction=result.idealized_return_pct,
            sigbot_realistic_result=result.realistic_return_pct,
            idealized_minus_realistic=result.gap_pct())


# ── Phase 3: gap detection ──────────────────────────────────────────────────
class GapStatus(str, Enum):
    ASSERTED = "asserted"            # hypothesized (e.g. by AI), not proven
    MEASURED = "measured"            # evidence from reality engine / validation
    UNVERIFIABLE = "unverifiable"    # cannot test with available data
    NOT_PRESENT = "not_present"      # tested and absent


@dataclass(frozen=True)
class GapEvidence:
    """A gap plus its status. A gap is MEASURED only with a numeric delta from
    the deterministic engine. An AI hypothesis can only ever set ASSERTED."""
    gap_id: str                      # e.g. "G10_market_impact"
    status: GapStatus
    measured_delta_pct: float | None = None   # only set when MEASURED
    note: str = ""

    def __post_init__(self) -> None:
        if self.status == GapStatus.MEASURED and self.measured_delta_pct is None:
            raise ValueError("MEASURED gap requires a numeric delta — no "
                             "measurement, no MEASURED status")
        if self.status != GapStatus.MEASURED and self.measured_delta_pct is not None:
            raise ValueError("only MEASURED gaps may carry a delta")


class GapRegistry:
    """Deterministic registry over the G1-G20 taxonomy. AI hypotheses land as
    ASSERTED; only the reality engine / validation battery can promote a gap to
    MEASURED via record_measurement()."""

    G_TAXONOMY = {
        "G1_lookahead", "G2_survivorship", "G3_data_revisions", "G4_selection",
        "G5_param_overfit", "G6_multiple_testing", "G7_unrealistic_fills",
        "G8_slippage", "G9_spread", "G10_market_impact", "G11_liquidity",
        "G12_hidden_leverage", "G13_correlation_concentration",
        "G14_regime_dependency", "G15_model_drift", "G16_calibration",
        "G17_execution_mismatch", "G18_broker_state", "G19_operational",
        "G20_permission",
    }

    def __init__(self) -> None:
        self._gaps: dict[str, GapEvidence] = {}

    def assert_gap(self, gap_id: str, note: str = "") -> None:
        """Record a HYPOTHESIS (e.g. from AI or static analysis). ASSERTED only —
        never proven by this call."""
        self._require_known(gap_id)
        # never downgrade a measured gap back to asserted
        if self._gaps.get(gap_id, None) and \
                self._gaps[gap_id].status == GapStatus.MEASURED:
            return
        self._gaps[gap_id] = GapEvidence(gap_id, GapStatus.ASSERTED, None, note)

    def record_measurement(self, gap_id: str, delta_pct: float,
                           note: str = "") -> None:
        """Promote a gap to MEASURED — ONLY the deterministic engine calls this,
        with a real numeric delta from the reality engine / validation."""
        self._require_known(gap_id)
        self._gaps[gap_id] = GapEvidence(gap_id, GapStatus.MEASURED,
                                         round(delta_pct, 3), note)

    def mark(self, gap_id: str, status: GapStatus, note: str = "") -> None:
        self._require_known(gap_id)
        self._gaps[gap_id] = GapEvidence(gap_id, status, None, note)

    def measured(self) -> list[GapEvidence]:
        return [g for g in self._gaps.values() if g.status == GapStatus.MEASURED]

    def asserted(self) -> list[GapEvidence]:
        return [g for g in self._gaps.values() if g.status == GapStatus.ASSERTED]

    def get(self, gap_id: str) -> GapEvidence | None:
        return self._gaps.get(gap_id)

    def _require_known(self, gap_id: str) -> None:
        if gap_id not in self.G_TAXONOMY:
            raise ValueError(f"unknown gap {gap_id}; not in G1-G20 taxonomy")


# ── Phase 4: controlled improvement generation ──────────────────────────────
# Map each actionable gap to the single causal component its fix touches.
_GAP_TO_FIX = {
    "G7_unrealistic_fills": (Component.EXECUTION, "fill at next executable bar"),
    "G8_slippage": (Component.EXECUTION, "liquidity-dependent slippage"),
    "G10_market_impact": (Component.LIQUIDITY, "cap order participation at % ADV"),
    "G11_liquidity": (Component.LIQUIDITY, "limit position to fraction of ADV"),
    "G2_survivorship": (Component.UNIVERSE, "remove survivorship-biased universe"),
    "G5_param_overfit": (Component.ENTRY_THRESHOLD, "widen/validate threshold"),
    "G13_correlation_concentration": (Component.SIZING, "cap single-name/sector"),
    "G14_regime_dependency": (Component.REGIME_FILTER, "validated regime filter"),
}


class ExperimentGenerator:
    """For each MEASURED (or strongly supported) actionable gap, generate ONE
    single-change experiment config. Never bundles fixes — one gap, one
    experiment, routed through the existing harness."""

    def generate(self, gap: GapEvidence, baseline_id: str,
                 splits: SplitConfig) -> ExperimentConfig | None:
        if gap.status != GapStatus.MEASURED:
            return None                # only fix what is proven
        fix = _GAP_TO_FIX.get(gap.gap_id)
        if fix is None:
            return None                # not actionable as a single change
        component, desc = fix
        change = Change(component, f"{gap.gap_id}: {desc}",
                        "baseline", desc)
        return ExperimentConfig(baseline_id, [change], splits)


# ── Phase 6: research ledger with full lineage ──────────────────────────────
@dataclass(frozen=True)
class LineageRecord:
    """The complete ancestry of one experiment: repo -> spec -> reproduction ->
    gap -> experiment -> result. Immutable; retained whether pass or reject."""
    repo_id: str
    spec_hash: str
    reproduction: ClaimRealityReport
    gap: GapEvidence
    experiment_hash: str
    verdict: Verdict
    reasons: tuple[str, ...]


class IntelligenceLedger:
    """Append-only lineage store. Rejected experiments are retained (killed
    hypotheses are information). A promoted strategy's accepted modifications can
    be traced back through their full ancestry."""

    def __init__(self) -> None:
        self._records: list[LineageRecord] = []

    def append(self, record: LineageRecord) -> None:
        self._records.append(record)

    def all(self) -> tuple[LineageRecord, ...]:
        return tuple(self._records)

    def accepted(self) -> tuple[LineageRecord, ...]:
        return tuple(r for r in self._records if r.verdict == Verdict.PASS)

    def rejected(self) -> tuple[LineageRecord, ...]:
        return tuple(r for r in self._records if r.verdict == Verdict.REJECT)

    def lineage_of(self, repo_id: str) -> tuple[LineageRecord, ...]:
        return tuple(r for r in self._records if r.repo_id == repo_id)

    def __len__(self) -> int:
        return len(self._records)


def _spec_hash(spec: StrategySpec) -> str:
    payload = {"repo": spec.repo_id, "universe": spec.universe.value,
               "timeframe": spec.timeframe.value,
               "indicators": [i.value for i in spec.indicators]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


# ── the AI boundary — advisory only, enforced by type ───────────────────────
@dataclass(frozen=True)
class Hypothesis:
    """The ONLY thing an AIAnalyst may return. It is advisory: it can raise a
    gap to ASSERTED or suggest a fix, but there is no code path from a Hypothesis
    to a P&L number, a MEASURED status, a verdict, or a capital authorization."""
    text: str
    suggested_gap_id: str | None = None


@runtime_checkable
class AIAnalyst(Protocol):
    """Advisory interface. Every method returns Hypothesis objects — never
    numbers, verdicts, or authorizations. The engine may ignore all of it."""

    def explain_code(self, snippet: str) -> Hypothesis: ...
    def propose_hidden_assumptions(self, docs: dict[str, str]) -> list[Hypothesis]: ...
    def suggest_missing_tests(self, spec: StrategySpec) -> list[Hypothesis]: ...
    def propose_single_gap_fix(self, gap_id: str) -> Hypothesis: ...


def ingest_ai_hypotheses(analyst: AIAnalyst, docs: dict[str, str],
                         registry: GapRegistry) -> int:
    """Feed AI hypotheses into the registry as ASSERTED only. Returns how many
    were recorded. This is the ONLY bridge from AI to the engine, and it can
    only ever produce ASSERTED gaps — never MEASURED, never a verdict."""
    n = 0
    for h in analyst.propose_hidden_assumptions(docs):
        if h.suggested_gap_id and h.suggested_gap_id in GapRegistry.G_TAXONOMY:
            registry.assert_gap(h.suggested_gap_id, note=f"AI: {h.text}")
            n += 1
    return n


# ── the orchestrator ────────────────────────────────────────────────────────
def analyze_repository(
    repo_id: str, docs: dict[str, str], intended_trades: list[SimTrade],
    splits: SplitConfig, baseline_fn, variant_fn,
    ledger: IntelligenceLedger, harness_ledger: ResearchLedger,
    analyst: AIAnalyst | None = None,
) -> tuple[ClaimRealityReport, GapRegistry, tuple[ExperimentResult, ...]]:
    """Full pipeline: spec -> reproduce -> measure gaps -> generate isolated
    experiments -> run through the sealed harness -> record lineage. Deterministic
    end to end; the AI (if any) only seeds ASSERTED hypotheses."""
    analyzer = RepositoryAnalyzer()
    spec = analyzer.build_spec(repo_id, docs, analyst)
    reproducer = StrategyReproducer()
    report = reproducer.reproduce(spec, intended_trades)

    registry = GapRegistry()
    if analyst is not None:
        ingest_ai_hypotheses(analyst, docs, registry)

    # Measure execution gaps from the reproduction's own breakdown (deterministic)
    real = simulate(intended_trades)
    for gap_id, delta in (("G10_market_impact", real.gap_breakdown.get("G10_impact", 0.0)),
                          ("G11_liquidity", real.gap_breakdown.get("G11_liquidity", 0.0)),
                          ("G7_unrealistic_fills", real.gap_breakdown.get("G7_next_bar", 0.0)),
                          ("G8_slippage", real.gap_breakdown.get("G8_slippage", 0.0))):
        if delta > 0.05:
            registry.record_measurement(gap_id, delta,
                                        note="reality-engine measured")

    gen = ExperimentGenerator()
    results: list[ExperimentResult] = []
    for gap in registry.measured():
        cfg = gen.generate(gap, repo_id, splits)
        if cfg is None:
            continue
        res = run_experiment(cfg, baseline_fn, variant_fn, harness_ledger)
        ledger.append(LineageRecord(
            repo_id, _spec_hash(spec), report, gap,
            res.config_hash, res.verdict, res.reasons))
        results.append(res)
    return report, registry, tuple(results)


def describe() -> str:
    return "\n".join([
        "STRATEGY INTELLIGENCE ENGINE — repo -> reproduction -> gap -> experiment",
        "",
        "  Takes an external strategy as RESEARCH INPUT (never a code template),",
        "  independently reconstructs it (provenance-tagged StrategySpec), runs it",
        "  through SIGBOT's own reality engine (the repo's P&L never enters),",
        "  detects gaps as MEASURED evidence (AI can only ASSERT), generates ONE-",
        "  gap-at-a-time experiments through the sealed harness, and records full",
        "  lineage (rejects retained).",
        "",
        "  AI = analyst (returns Hypothesis only — advisory). Engine = judge",
        "  (the only thing that measures, decides, promotes). No code path turns",
        "  an AI output into a P&L number, a MEASURED gap, a verdict, or capital.",
        "  Builds only on shipped components; adds no alpha, no broker.",
    ])
