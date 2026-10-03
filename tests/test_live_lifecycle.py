"""Live lifecycle — earns every state, two gates to live, zero-state record."""
import pytest

from sigbot.live_lifecycle import (
    IllegalTransition, LIVE_READINESS_GATES, LifecycleState, LiveLifecycle,
    LiveRecord, build_live_readiness_report)


def _lc(version="SIGBOT-INFLECTION-002"):
    return LiveLifecycle(champion_version=version)


def _to_candidate(lc):
    lc.advance(LifecycleState.HISTORICAL_VALIDATION)
    lc.advance(LifecycleState.OOS_VALIDATION)
    lc.advance(LifecycleState.PAPER_VALIDATION)
    for g in LIVE_READINESS_GATES:
        lc.pass_gate(g)
    lc.advance(LifecycleState.LIVE_CANDIDATE)
    return lc


# ── starts locked, never defaults to live ───────────────────────────────────
def test_starts_building_and_locked():
    lc = _lc()
    assert lc.state == LifecycleState.BUILDING
    assert lc.capital_label() == "LOCKED"


def test_advance_cannot_skip_stages():
    lc = _lc()
    with pytest.raises(IllegalTransition):
        lc.advance(LifecycleState.PAPER_VALIDATION)   # skipped historical+oos


def test_advance_cannot_reach_live():
    lc = _to_candidate(_lc())
    with pytest.raises(IllegalTransition):
        lc.advance(LifecycleState.LIVE)


# ── gates ───────────────────────────────────────────────────────────────────
def test_candidate_requires_all_gates():
    lc = _lc()
    lc.advance(LifecycleState.HISTORICAL_VALIDATION)
    lc.advance(LifecycleState.OOS_VALIDATION)
    lc.advance(LifecycleState.PAPER_VALIDATION)
    lc.pass_gate("historical_validation")       # only one
    with pytest.raises(IllegalTransition):
        lc.advance(LifecycleState.LIVE_CANDIDATE)


def test_unknown_gate_rejected():
    lc = _lc()
    with pytest.raises(ValueError):
        lc.pass_gate("make_money_gate")


def test_missing_gates_listed():
    lc = _lc()
    lc.pass_gate("historical_validation")
    assert "oos_validation" in lc.missing_gates()
    assert "historical_validation" not in lc.missing_gates()


# ── live_candidate is still locked ──────────────────────────────────────────
def test_candidate_capital_still_locked():
    lc = _to_candidate(_lc())
    assert lc.state == LifecycleState.LIVE_CANDIDATE
    assert lc.capital_label() == "LOCKED"
    assert not lc.capital_authorized()


# ── the human gate ──────────────────────────────────────────────────────────
def test_activation_requires_human_approval():
    lc = _to_candidate(_lc())
    with pytest.raises(IllegalTransition):
        lc.activate_live("SIGBOT-INFLECTION-002", "2027-01-01", human_approved=False)


def test_activation_requires_matching_version():
    lc = _to_candidate(_lc())
    with pytest.raises(IllegalTransition):
        lc.activate_live("WRONG-VERSION", "2027-01-01", human_approved=True)


def test_activation_requires_candidate_state():
    lc = _lc()  # still BUILDING
    with pytest.raises(IllegalTransition):
        lc.activate_live("SIGBOT-INFLECTION-002", "2027-01-01", human_approved=True)


def test_proper_activation_goes_live_and_authorizes():
    lc = _to_candidate(_lc())
    lc.activate_live("SIGBOT-INFLECTION-002", "2027-01-01", human_approved=True)
    assert lc.state == LifecycleState.LIVE
    assert lc.capital_authorized()
    assert lc.capital_label() == "AUTHORIZED"


# ── zero-state live record ──────────────────────────────────────────────────
def test_live_record_starts_at_zero():
    lc = _to_candidate(_lc())
    lc.activate_live("SIGBOT-INFLECTION-002", "2027-01-01T00:00", human_approved=True)
    ps = lc.public_state()
    assert ps["live_days"] == 0
    assert ps["live_trades"] == 0
    assert ps["live_pnl"] == 0.0
    assert ps["live_drawdown_pct"] == 0.0
    assert lc.live_record.activated_at == "2027-01-01T00:00"


def test_no_live_record_before_activation():
    lc = _to_candidate(_lc())
    assert lc.public_state()["has_live_record"] is False


def test_live_record_zero_factory():
    r = LiveRecord.zero("2027-01-01")
    assert r.days == 0 and r.trades == 0 and r.pnl == 0.0


# ── fail-to-safe from any state including live ──────────────────────────────
def test_pause_from_live_blocks_capital():
    lc = _to_candidate(_lc())
    lc.activate_live("SIGBOT-INFLECTION-002", "2027-01-01", human_approved=True)
    assert lc.capital_authorized()
    lc.pause_trading("broker drift")
    assert lc.state == LifecycleState.TRADING_PAUSED
    assert not lc.capital_authorized()


def test_quarantine_from_live_blocks_capital():
    lc = _to_candidate(_lc())
    lc.activate_live("SIGBOT-INFLECTION-002", "2027-01-01", human_approved=True)
    lc.quarantine("health drift")
    assert lc.state == LifecycleState.QUARANTINED
    assert not lc.capital_authorized()


def test_cannot_advance_from_failure_state():
    lc = _lc()
    lc.quarantine("x")
    with pytest.raises(IllegalTransition):
        lc.advance(LifecycleState.HISTORICAL_VALIDATION)


# ── readiness report never claims live ──────────────────────────────────────
def test_readiness_report_says_candidate_not_live():
    lc = _to_candidate(_lc())
    report = build_live_readiness_report(lc)
    assert "LIVE CANDIDATE" in report
    assert "awaiting human activation" in report
    assert "CAPITAL   LOCKED" in report


def test_readiness_report_shows_incomplete():
    lc = _lc()
    lc.pass_gate("historical_validation")
    report = build_live_readiness_report(lc)
    assert "NOT YET ELIGIBLE" in report


# ── no shortcut methods ─────────────────────────────────────────────────────
def test_no_go_live_shortcut():
    lc = _lc()
    assert not hasattr(lc, "go_live")
    assert not hasattr(lc, "force_live")
    assert not hasattr(lc, "enable_capital")
