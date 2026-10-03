"""24/7 operating loop — diagnostics, quarantine, recovery, isolation, decisions."""


import pytest

from sigbot.operating_loop import (
    CheckCategory, CommandCenter, CycleTracker, DecisionInputs,
    DiagnosticCheck, ModelLifecycle, ModelState, OperationalReadinessPolicy,
    RECOVERY_CHECKS, SystemDiagnosticEngine, TradeDecision,
    authorize_through_lifecycle, decide, trace_root_cause)
from sigbot.system_assurance import (
    ApprovedChampion, ExperimentLeakError, ModelOrigin, TradeAuthRequest)

CHAMP = ApprovedChampion("SIGBOT-INFLECTION-001", "v2.0", "2026-01-01", "gen-001")


def _check(cat, passed, layer):
    return DiagnosticCheck(cat, f"{cat.value}", passed, layer=layer)


# ── item 4/5: classification ────────────────────────────────────────────────
def test_all_pass_is_healthy():
    d = SystemDiagnosticEngine()
    assert d.classify([_check(CheckCategory.DATA_INTEGRITY, True, "data")]) == ModelState.HEALTHY


def test_critical_failure_quarantines():
    d = SystemDiagnosticEngine()
    assert d.classify([_check(CheckCategory.DATA_INTEGRITY, False, "data")]) == ModelState.QUARANTINED


def test_reconciliation_failure_pauses_system():
    d = SystemDiagnosticEngine()
    assert d.classify([_check(CheckCategory.RECONCILIATION, False, "risk")]) == ModelState.SYSTEM_PAUSED


def test_capital_path_failure_pauses_system():
    d = SystemDiagnosticEngine()
    assert d.classify([_check(CheckCategory.CAPITAL_PATH, False, "risk")]) == ModelState.SYSTEM_PAUSED


def test_single_noncritical_is_warning():
    d = SystemDiagnosticEngine()
    assert d.classify([_check(CheckCategory.EXECUTION_COST, False, "risk")]) == ModelState.WARNING


# ── item 6: root-cause tracing (earliest broken layer) ──────────────────────
def test_stale_website_blames_website_not_model():
    failed = [_check(CheckCategory.WEBSITE_CONSISTENCY, False, "website")]
    assert trace_root_cause(failed) == "website"


def test_data_corruption_blames_data_not_symptom():
    failed = [_check(CheckCategory.PREDICTION_INTEGRITY, False, "prediction"),
              _check(CheckCategory.DATA_INTEGRITY, False, "data")]
    assert trace_root_cause(failed) == "data"   # earliest layer, not the symptom


def test_db_api_fine_website_stale_blames_website():
    failed = [_check(CheckCategory.WEBSITE_CONSISTENCY, False, "website")]
    assert trace_root_cause(failed) == "website"


# ── item 3: production isolation ────────────────────────────────────────────
def test_quarantined_model_cannot_trade():
    lc = ModelLifecycle("stocks", state=ModelState.QUARANTINED, champion=CHAMP)
    req = TradeAuthRequest("SIGBOT-INFLECTION-001", ModelOrigin.PRODUCTION, "gen-001")
    with pytest.raises(ExperimentLeakError):
        authorize_through_lifecycle(req, lc)


def test_active_champion_can_trade():
    lc = ModelLifecycle("stocks", state=ModelState.ACTIVE, champion=CHAMP)
    req = TradeAuthRequest("SIGBOT-INFLECTION-001", ModelOrigin.PRODUCTION, "gen-001")
    assert authorize_through_lifecycle(req, lc) is True


def test_research_model_blocked_through_lifecycle():
    lc = ModelLifecycle("stocks", state=ModelState.ACTIVE, champion=CHAMP)
    req = TradeAuthRequest("candidate-9", ModelOrigin.RESEARCH, "gen-002")
    with pytest.raises(ExperimentLeakError):
        authorize_through_lifecycle(req, lc)


# ── item 9: recovery only on ALL mandatory checks ───────────────────────────
def test_quarantined_stays_until_all_checks_pass():
    lc = ModelLifecycle("stocks", state=ModelState.QUARANTINED, champion=CHAMP)
    partial = set(list(RECOVERY_CHECKS)[:6])
    assert lc.attempt_recovery(partial) == ModelState.RECOVERY   # not cleared
    assert not lc.can_authorize_capital()


def test_full_recovery_reactivates():
    lc = ModelLifecycle("stocks", state=ModelState.QUARANTINED, champion=CHAMP)
    assert lc.attempt_recovery(set(RECOVERY_CHECKS)) == ModelState.ACTIVE
    assert lc.can_authorize_capital()


def test_recovery_ignores_returns_and_opinion():
    """Recovery requires checks, not 'returns improved' — there's no such path."""
    lc = ModelLifecycle("stocks", state=ModelState.QUARANTINED, champion=CHAMP)
    # even with most checks, one missing keeps it out
    almost = set(RECOVERY_CHECKS) - {"end_to_end_canary"}
    assert lc.attempt_recovery(almost) == ModelState.RECOVERY
    assert not lc.can_authorize_capital()


# ── item 11: decision architecture ──────────────────────────────────────────
def _inp(**kw):
    base = dict(expected_edge=5.0, historical_confidence=0.8, downside=4.0,
                liquidity_ok=True, portfolio_correlation=0.2,
                existing_exposure_pct=0.1, model_state=ModelState.ACTIVE)
    base.update(kw)
    return DecisionInputs(**base)


def test_negative_edge_is_no_trade():
    assert decide(_inp(expected_edge=-0.1)) == TradeDecision.NO_TRADE


def test_illiquid_is_no_trade():
    assert decide(_inp(liquidity_ok=False)) == TradeDecision.NO_TRADE


def test_quarantined_model_decision_is_pause():
    assert decide(_inp(model_state=ModelState.QUARANTINED)) == TradeDecision.PAUSE


def test_crowded_book_is_small_trade():
    assert decide(_inp(existing_exposure_pct=0.4)) == TradeDecision.SMALL_TRADE


def test_high_correlation_is_small_trade():
    assert decide(_inp(portfolio_correlation=0.9)) == TradeDecision.SMALL_TRADE


def test_insufficient_reward_for_risk_is_wait():
    assert decide(_inp(expected_edge=0.5, downside=10.0)) == TradeDecision.WAIT


def test_good_setup_trades():
    assert decide(_inp()) == TradeDecision.TRADE


# ── item 12: command center ─────────────────────────────────────────────────
def test_system_safe_only_with_active_and_no_pause():
    cc = CommandCenter()
    cc.register(ModelLifecycle("stocks", state=ModelState.ACTIVE, champion=CHAMP))
    assert cc.system_safe_to_operate()


def test_system_pause_makes_unsafe():
    cc = CommandCenter()
    cc.register(ModelLifecycle("stocks", state=ModelState.ACTIVE, champion=CHAMP))
    cc.register(ModelLifecycle("crypto", state=ModelState.SYSTEM_PAUSED, champion=CHAMP))
    assert not cc.system_safe_to_operate()
    assert "crypto" in cc.paused_models()


# ── item 1: cycle verification ──────────────────────────────────────────────
def test_missing_cycle_detected():
    t = CycleTracker()
    t.expect("stocks", 3)
    t.complete("stocks")
    assert t.missing_cycles() == {"stocks": 2}
    assert not t.all_cycles_ran()


def test_all_cycles_ran():
    t = CycleTracker()
    t.expect("news", 2)
    t.complete("news")
    t.complete("news")
    assert t.all_cycles_ran()


# ── item 7: incidents preserved ─────────────────────────────────────────────
def test_incident_recorded_and_preserved():
    d = SystemDiagnosticEngine()
    lc = ModelLifecycle("stocks", champion=CHAMP)
    inc = d.diagnose("stocks", [_check(CheckCategory.DATA_INTEGRITY, False, "data")])
    lc.record_incident(inc)
    assert len(lc.incidents) == 1
    assert lc.state == ModelState.QUARANTINED
    assert lc.incidents[0].root_cause_layer == "data"


# ── item 13: readiness policy is versioned ──────────────────────────────────
def test_readiness_policy_versioned_and_complete():
    p = OperationalReadinessPolicy()
    assert p.version == "orp-v1"
    assert not p.ready(set())                 # nothing passes
    assert p.ready(set(RECOVERY_CHECKS))      # all pass
    assert len(p.missing({"data_integrity"})) == len(RECOVERY_CHECKS) - 1
