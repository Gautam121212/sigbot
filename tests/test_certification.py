"""Certification framework — time-lock, snapshot, timing validation, replay."""
import pytest
from datetime import date, timedelta

from sigbot.certification import (
    CertificationReport, FrozenReplayConfig,
    LookaheadViolation, ModelVerdict, PromotionRecord, ReplayTrade, SimulationClock, WalkForwardResult, _verdict,
    build_snapshot, run_replay_a)


def _trade(decision_d, entry_d, exit_d, ret=0.05, model="stocks", sym="AAPL"):
    return ReplayTrade(f"T-{entry_d}", model, sym, "BUY", entry_d, exit_d,
                       100.0, 105.0, ret, ret - 0.001, 10.0, decision_d)


# ── time-lock ────────────────────────────────────────────────────────────────
def test_clock_blocks_future_data():
    clock = SimulationClock(date(2020, 6, 15))
    with pytest.raises(LookaheadViolation):
        clock.require_available_at(date(2020, 6, 16), "price")


def test_clock_allows_same_day():
    clock = SimulationClock(date(2020, 6, 15))
    clock.require_available_at(date(2020, 6, 15), "price")   # no raise


def test_clock_allows_past():
    clock = SimulationClock(date(2020, 6, 15))
    clock.require_available_at(date(2019, 1, 1), "fundamental")


def test_clock_records_violations():
    clock = SimulationClock(date(2020, 1, 1))
    try:
        clock.require_available_at(date(2020, 1, 2))
    except LookaheadViolation:
        pass
    assert len(clock.violations()) == 1


def test_clock_cannot_go_backward():
    clock = SimulationClock(date(2020, 6, 15))
    with pytest.raises(ValueError):
        clock.advance(date(2020, 6, 14))


# ── timing validation ────────────────────────────────────────────────────────
def test_decision_before_entry_is_valid():
    t = _trade(date(2020, 1, 3), date(2020, 1, 4), date(2020, 1, 10))
    assert t.valid_timing()


def test_decision_after_entry_invalid():
    t = _trade(date(2020, 1, 5), date(2020, 1, 4), date(2020, 1, 10))
    assert not t.valid_timing()


def test_entry_after_exit_invalid():
    t = _trade(date(2020, 1, 3), date(2020, 1, 10), date(2020, 1, 4))
    assert not t.valid_timing()


# ── snapshot sealing ─────────────────────────────────────────────────────────
def test_snapshot_verifies_same_config():
    s = build_snapshot("v1", {"p": 1}, {"t": 0.5})
    assert s.verify(s.config_hash, s.parameters_hash)


def test_snapshot_fails_changed_config():
    s = build_snapshot("v1", {"p": 1}, {"t": 0.5})
    assert not s.verify("different", s.parameters_hash)


def test_snapshot_id_unique():
    import time
    s1 = build_snapshot("v1", {}, {})
    time.sleep(0.01)
    s2 = build_snapshot("v1", {}, {})
    assert s1.snapshot_id != s2.snapshot_id


# ── replay A ────────────────────────────────────────────────────────────────
def test_replay_a_runs_clean():
    cfg = FrozenReplayConfig(date(2020, 1, 1), date(2020, 1, 10), 100_000)
    entry = date(2020, 1, 4)
    result = run_replay_a(cfg, lambda clock: [
        _trade(entry - timedelta(days=1), entry, date(2020, 1, 10))
    ] if clock.current_date == entry else [])
    assert result.lookahead_clean()
    assert len(result.trades) == 1
    s = result.summary()
    assert s["timing_violations"] == 0
    assert s["lookahead_violations"] == 0


def test_replay_a_catches_timing_violation():
    cfg = FrozenReplayConfig(date(2020, 1, 1), date(2020, 1, 10))
    entry = date(2020, 1, 4)
    # decision AFTER entry — bad
    bad = _trade(entry + timedelta(days=1), entry, date(2020, 1, 10))
    result = run_replay_a(cfg, lambda clock: [bad]
                          if clock.current_date == entry else [])
    assert result.summary()["timing_violations"] == 1


def test_replay_a_equity_curve():
    cfg = FrozenReplayConfig(date(2020, 1, 1), date(2020, 1, 5))
    result = run_replay_a(cfg, lambda _: [])
    # one entry per day (including start and all advances)
    assert len(result.equity_curve) > 1
    assert result.equity_curve[0][1] == cfg.starting_capital


# ── walk-forward model history ───────────────────────────────────────────────
def test_promotion_cannot_alter_past():
    wf = WalkForwardResult(promotions=[
        PromotionRecord("v1", date(2013, 1, 1)),
        PromotionRecord("v2", date(2017, 4, 11), "v1"),
    ])
    assert wf.active_model_at(date(2015, 6, 1)) == "v1"
    assert wf.active_model_at(date(2018, 1, 1)) == "v2"
    assert wf.active_model_at(date(2017, 4, 10)) == "v1"   # day before promotion


def test_no_model_before_first_promotion():
    wf = WalkForwardResult(promotions=[
        PromotionRecord("v1", date(2015, 1, 1)),
    ])
    assert wf.active_model_at(date(2014, 12, 31)) is None


# ── model verdicts ───────────────────────────────────────────────────────────
def test_negative_cagr_fails():
    v, _ = _verdict(-3.0, 0.8, 0.55, 100)
    assert v == ModelVerdict.FAILED


def test_insufficient_trades_inconclusive():
    v, _ = _verdict(15.0, 1.2, 0.60, 20)
    assert v == ModelVerdict.INCONCLUSIVE


def test_low_sharpe_warning():
    v, _ = _verdict(8.0, 0.4, 0.55, 100)
    assert v == ModelVerdict.SURVIVED_WITH_WARNING


def test_good_result_survives():
    v, _ = _verdict(14.0, 1.58, 0.594, 1703)
    assert v == ModelVerdict.SURVIVED


# ── governance summary ───────────────────────────────────────────────────────
def test_governance_certifiable_only_when_clean():
    cfg = FrozenReplayConfig(date(2020, 1, 1), date(2020, 1, 3))
    result = run_replay_a(cfg, lambda _: [])
    report = CertificationReport(result.snapshot, result)
    # replay_b not run -> not certifiable (correct — can't be certified half-done)
    assert not report.governance_summary()["certifiable"]


def test_both_replays_clean_certifiable():
    cfg = FrozenReplayConfig(date(2020, 1, 1), date(2020, 1, 3))
    result = run_replay_a(cfg, lambda _: [])
    wf = WalkForwardResult()          # empty but no violations
    report = CertificationReport(result.snapshot, result, wf)
    assert report.governance_summary()["certifiable"]
