"""Strategy intelligence engine — repo -> reproduction -> gap -> experiment.

Covers all 12 required areas: spec extraction, documented-vs-inferred, reproduction
independence, external-P&L rejection, measured-vs-asserted gaps, one-fix generation,
harness-bypass impossibility, sealed-OOS inaccessibility, complete lineage,
reproducibility, rejected-hypothesis persistence, AI-never-a-verdict."""
import pytest

from sigbot.improvement_harness import (
    LockedSplit, ResearchLedger, SplitConfig, SplitResult)
from sigbot.reality_engine import SimTrade
from sigbot.strategy_intelligence_engine import (
    AIAnalyst, ExperimentGenerator, GapEvidence, GapRegistry, GapStatus,
    Hypothesis, IntelligenceLedger, Provenance, RepositoryAnalyzer,
    StrategyReproducer, analyze_repository, ingest_ai_hypotheses)


def _docs():
    return {"universe": "US large-cap", "timeframe": "daily",
            "indicators": "RSI,MACD", "claimed_performance": "+80% CAGR"}


def _splits():
    return SplitConfig("2019-12-31", "2021-12-31", "2024-12-31")


def _trades():
    return ([SimTrade(f"S{i}", 0.08, 50000, 2_000_000) for i in range(20)]
            + [SimTrade(f"I{i}", 0.15, 500000, 1_000_000) for i in range(5)])


class _AI:
    def explain_code(self, snippet): return Hypothesis("same-bar fill?")
    def propose_hidden_assumptions(self, docs):
        return [Hypothesis("orders exceed ADV", "G10_market_impact")]
    def suggest_missing_tests(self, spec): return [Hypothesis("test liquidity")]
    def propose_single_gap_fix(self, gap_id): return Hypothesis(f"fix {gap_id}")


# ── 1. spec extraction ──────────────────────────────────────────────────────
def test_spec_extraction():
    spec = RepositoryAnalyzer().build_spec("r", _docs())
    assert spec.universe.value == "US large-cap"
    assert len(spec.indicators) == 2


# ── 2. documented vs inferred separation ────────────────────────────────────
def test_documented_vs_inferred_separated():
    spec = RepositoryAnalyzer().build_spec("r", _docs(), _AI())
    assert all(f.provenance == Provenance.DOCUMENTED for f in spec.documented_fields())
    # AI hypotheses land as INFERRED, never documented
    assert all(f.provenance == Provenance.INFERRED for f in spec.inferred_fields())
    assert spec.inferred_fields()      # the AI added at least one


def test_missing_field_is_unverifiable_not_fact():
    spec = RepositoryAnalyzer().build_spec("r", {"universe": "US"})
    # timeframe wasn't in docs -> unverifiable, never asserted as fact
    assert spec.timeframe.provenance == Provenance.UNVERIFIABLE


# ── 3. reproduction independence ────────────────────────────────────────────
def test_reproduction_computes_sigbot_own_numbers():
    spec = RepositoryAnalyzer().build_spec("r", _docs())
    report = StrategyReproducer().reproduce(spec, _trades())
    assert report.sigbot_realistic_result < report.sigbot_idealized_reproduction


# ── 4. external P&L rejection ───────────────────────────────────────────────
def test_external_pnl_never_enters_accounting():
    """The +80% claim is a STRING; SIGBOT's numbers are computed, not read."""
    spec = RepositoryAnalyzer().build_spec("r", _docs())
    report = StrategyReproducer().reproduce(spec, _trades())
    assert report.published_claim == "+80% CAGR"          # kept as context
    assert isinstance(report.sigbot_idealized_reproduction, float)
    # the claim string cannot be coerced into the computed number
    assert "80" not in str(report.sigbot_realistic_result)


# ── 5. measured vs asserted gap classification ──────────────────────────────
def test_ai_assertion_is_only_asserted():
    reg = GapRegistry()
    reg.assert_gap("G10_market_impact", "AI hunch")
    assert reg.get("G10_market_impact").status == GapStatus.ASSERTED
    assert reg.get("G10_market_impact").measured_delta_pct is None


def test_measured_requires_numeric_delta():
    with pytest.raises(ValueError):
        GapEvidence("G10_market_impact", GapStatus.MEASURED)   # no delta


def test_only_engine_measurement_promotes_gap():
    reg = GapRegistry()
    reg.assert_gap("G10_market_impact")
    reg.record_measurement("G10_market_impact", 2.4)
    g = reg.get("G10_market_impact")
    assert g.status == GapStatus.MEASURED and g.measured_delta_pct == 2.4


def test_measurement_not_downgraded_by_later_assertion():
    reg = GapRegistry()
    reg.record_measurement("G10_market_impact", 2.4)
    reg.assert_gap("G10_market_impact")               # should not overwrite
    assert reg.get("G10_market_impact").status == GapStatus.MEASURED


# ── 6. one-fix experiment generation ────────────────────────────────────────
def test_generates_single_change_experiment():
    reg = GapRegistry()
    reg.record_measurement("G10_market_impact", 2.4)
    cfg = ExperimentGenerator().generate(reg.get("G10_market_impact"),
                                         "base", _splits())
    assert cfg is not None
    assert len(cfg.changes) == 1                      # exactly one


def test_unmeasured_gap_generates_no_experiment():
    reg = GapRegistry()
    reg.assert_gap("G10_market_impact")               # only asserted
    cfg = ExperimentGenerator().generate(reg.get("G10_market_impact"),
                                         "base", _splits())
    assert cfg is None                                # won't fix an unproven gap


# ── 7. cannot bypass the improvement harness ────────────────────────────────
def test_experiments_go_through_harness_and_are_recorded():
    def base():
        return (SplitResult(5, 1.5, 17, 59, 100),
                SplitResult(5, 1.5, 17, 59, 100), LockedSplit(1.5))
    def variant():
        return (SplitResult(6, 1.7, 16, 60, 100),
                SplitResult(6, 1.7, 16, 60, 100), LockedSplit(1.7))
    il, hl = IntelligenceLedger(), ResearchLedger()
    _, _, results = analyze_repository("r", _docs(), _trades(), _splits(),
                                       base, variant, il, hl, _AI())
    # every experiment recorded in the harness ledger (the only decision path)
    assert len(hl) == len(results) > 0


# ── 8. cannot access sealed OOS during fitting ──────────────────────────────
def test_sealed_oos_blocks_access_during_fitting():
    locked = LockedSplit(1.7)
    from sigbot.improvement_harness import SplitLeakageError
    with pytest.raises(SplitLeakageError):
        locked.read()                                 # sealed until decision


# ── 9. complete experiment lineage ──────────────────────────────────────────
def test_complete_lineage_recorded():
    def base():
        return (SplitResult(5, 1.5, 17, 59, 100),
                SplitResult(5, 1.5, 17, 59, 100), LockedSplit(1.5))
    def variant():
        return (SplitResult(6, 1.7, 16, 60, 100),
                SplitResult(6, 1.7, 16, 60, 100), LockedSplit(1.7))
    il, hl = IntelligenceLedger(), ResearchLedger()
    analyze_repository("github/x", _docs(), _trades(), _splits(),
                       base, variant, il, hl, _AI())
    rec = il.all()[0]
    # every ancestry link present
    assert rec.repo_id == "github/x"
    assert rec.spec_hash and rec.experiment_hash
    assert rec.reproduction.published_claim == "+80% CAGR"
    assert rec.gap.status == GapStatus.MEASURED


# ── 10. deterministic reproducibility ───────────────────────────────────────
def test_deterministic_reproducibility():
    def base():
        return (SplitResult(5, 1.5, 17, 59, 100),
                SplitResult(5, 1.5, 17, 59, 100), LockedSplit(1.5))
    def variant():
        return (SplitResult(6, 1.7, 16, 60, 100),
                SplitResult(6, 1.7, 16, 60, 100), LockedSplit(1.7))
    out1 = analyze_repository("r", _docs(), _trades(), _splits(), base,
                              variant, IntelligenceLedger(), ResearchLedger())
    out2 = analyze_repository("r", _docs(), _trades(), _splits(), base,
                              variant, IntelligenceLedger(), ResearchLedger())
    v1 = [r.verdict for r in out1[2]]
    v2 = [r.verdict for r in out2[2]]
    assert v1 == v2


# ── 11. rejected-hypothesis persistence ─────────────────────────────────────
def test_rejected_experiments_retained():
    def base():
        return (SplitResult(5, 1.5, 17, 59, 100),
                SplitResult(5, 1.5, 17, 59, 100), LockedSplit(1.5))
    def worse():
        return (SplitResult(9, 1.2, 25, 45, 100),
                SplitResult(9, 1.2, 25, 45, 100), LockedSplit(1.2))
    il, hl = IntelligenceLedger(), ResearchLedger()
    analyze_repository("r", _docs(), _trades(), _splits(), base, worse,
                       il, hl, _AI())
    assert len(il.rejected()) > 0                     # failures retained
    assert len(il) == len(il.accepted()) + len(il.rejected())


# ── 12. AI output never becomes a verdict ───────────────────────────────────
def test_ai_conforms_and_returns_only_hypotheses():
    ai = _AI()
    assert isinstance(ai, AIAnalyst)
    assert isinstance(ai.explain_code("x"), Hypothesis)
    assert all(isinstance(h, Hypothesis)
               for h in ai.propose_hidden_assumptions(_docs()))


def test_ai_hypothesis_only_produces_asserted_gap():
    """The only AI->engine bridge yields ASSERTED, never MEASURED or a verdict."""
    reg = GapRegistry()
    n = ingest_ai_hypotheses(_AI(), _docs(), reg)
    assert n == 1
    assert reg.get("G10_market_impact").status == GapStatus.ASSERTED
    # no MEASURED gap was created by the AI
    assert not reg.measured()


def test_hypothesis_has_no_pnl_or_verdict_field():
    """Structurally, a Hypothesis cannot carry a number or a decision."""
    h = Hypothesis("x", "G10_market_impact")
    assert not hasattr(h, "verdict")
    assert not hasattr(h, "pnl")
    assert not hasattr(h, "measured_delta")
