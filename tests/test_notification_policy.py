"""Notification policy engine — classification, aggregation, the acceptance test."""
from datetime import datetime, timedelta, timezone

from sigbot.notification_policy import (
    Event, NotificationClass, NotificationPolicyEngine, base_class)

BASE = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)


def _eng():
    return NotificationPolicyEngine()


# ── classification table ────────────────────────────────────────────────────
def test_critical_types_classified_critical():
    for t in ("broker_position_mismatch", "trading_paused",
              "risk_firewall_failure", "lookahead_violation_production"):
        assert base_class(t) == NotificationClass.CRITICAL


def test_important_types_classified_important():
    for t in ("model_quarantined", "lifecycle_stage_change",
              "model_live_candidate", "incident_recovered"):
        assert base_class(t) == NotificationClass.IMPORTANT


def test_routine_types_are_silent():
    for t in ("scheduler_tick", "heartbeat", "prediction_created",
              "research_hypothesis", "scan_success", "model_started",
              "paper_trade_normal", "status_unchanged"):
        assert base_class(t) == NotificationClass.SILENT


def test_unknown_type_is_silent_by_default():
    """Opt IN to interrupting — a new event type never spams by default."""
    assert base_class("some_brand_new_event") == NotificationClass.SILENT


def test_digest_types_roll_into_daily():
    for t in ("paper_signal", "research_generated", "research_oos"):
        assert base_class(t) == NotificationClass.DAILY_DIGEST


# ── silent/digest never interrupt ───────────────────────────────────────────
def test_silent_event_sends_nothing():
    d = _eng().classify(Event("heartbeat", BASE))
    assert not d.send_now


def test_digest_event_counts_but_sends_nothing():
    eng = _eng()
    for _ in range(50):
        d = eng.classify(Event("paper_signal", BASE))
        assert not d.send_now
    assert eng.daily_counts()["paper_signal"] == 50


# ── THE ACCEPTANCE TEST ─────────────────────────────────────────────────────
def test_acceptance_normal_day_zero_routine_alerts():
    """Thousands of routine events -> zero Telegram alerts."""
    eng = _eng()
    routine = ["scheduler_tick", "model_started", "model_finished",
               "prediction_created", "research_hypothesis", "research_rejected",
               "scan_success", "heartbeat", "paper_trade_normal",
               "prediction_resolved_normal", "data_refresh", "db_update"]
    sent = 0
    for i in range(3000):
        d = eng.classify(Event(routine[i % len(routine)],
                               BASE + timedelta(seconds=i)))
        if d.send_now:
            sent += 1
    assert sent == 0


def test_acceptance_one_incident_one_alert_one_recovery():
    eng = _eng()
    inc = "INC-204"
    # open
    assert eng.classify(Event("critical_data_failure_active_model", BASE,
                              incident_id=inc, affects_capital=True)).send_now
    # repeats silent
    for i in range(10):
        d = eng.classify(Event("critical_data_failure_active_model",
                               BASE + timedelta(seconds=i + 1), incident_id=inc))
        assert not d.send_now
    # recovery once
    rec = eng.classify(Event("critical_data_failure_active_model",
                             BASE + timedelta(minutes=5), incident_id=inc,
                             is_recovery=True))
    assert rec.send_now
    # recovery again silent
    rec2 = eng.classify(Event("critical_data_failure_active_model",
                              BASE + timedelta(minutes=6), incident_id=inc,
                              is_recovery=True))
    assert not rec2.send_now


def test_acceptance_restart_mid_incident_no_duplicate():
    eng = _eng()
    inc = "INC-300"
    eng.classify(Event("broker_position_mismatch", BASE, incident_id=inc,
                       affects_capital=True))
    snap = eng.snapshot()
    eng2 = _eng()
    eng2.restore(snap)
    d = eng2.classify(Event("broker_position_mismatch",
                            BASE + timedelta(minutes=1), incident_id=inc))
    assert not d.send_now


# ── root-cause aggregation ──────────────────────────────────────────────────
def test_downstream_failures_fold_into_root_incident():
    eng = _eng()
    root = "INC-500"
    assert eng.classify(Event("critical_data_failure_active_model", BASE,
                              incident_id=root, affects_capital=True)).send_now
    # five downstream effects of the same root -> zero extra alerts
    for child in ("trading_paused", "model_quarantined_production",
                  "model_quarantined", "sla_missed", "required_source_unavailable"):
        d = eng.classify(Event(child, BASE + timedelta(seconds=5),
                               root_incident_id=root))
        assert not d.send_now
    assert eng.children_of(root) == 5


# ── oscillation / flap protection ───────────────────────────────────────────
def test_repeats_of_open_incident_are_silent():
    """Rapid repeats of a still-open incident (never recovering) = chatty
    failure, not oscillation — only the opener alerts."""
    eng = _eng()
    inc = "INC-CHATTY"
    sends = [eng.classify(Event("model_quarantined", BASE + timedelta(minutes=i),
                                incident_id=inc)).send_now
             for i in range(10)]
    assert sum(sends) == 1          # only the opening alert


def test_oscillation_flap_produces_grouped_alert():
    """True oscillation = reopen after recovery, repeatedly. After the flap
    threshold, a single grouped alert fires and further flaps are suppressed."""
    eng = _eng()
    inc = "INC-FLAP"
    sends = 0
    t = BASE
    for _ in range(8):
        # open
        if eng.classify(Event("model_quarantined", t, incident_id=inc)).send_now:
            sends += 1
        t += timedelta(minutes=1)
        # recover
        eng.classify(Event("model_quarantined", t, incident_id=inc,
                           is_recovery=True))
        t += timedelta(minutes=1)
    # opener + a handful of reopens + one grouped alert, then suppressed.
    # The key property: it does NOT send 8 separate flap alerts.
    assert sends < 8
    assert sends >= 2


# ── one-off state change with no incident id ────────────────────────────────
def test_lifecycle_change_sends_once():
    eng = _eng()
    d = eng.classify(Event("model_live_candidate", BASE))
    assert d.send_now


# ── read-only / calculates nothing ──────────────────────────────────────────
def test_engine_has_no_send_or_calc_methods():
    eng = _eng()
    assert not hasattr(eng, "send_telegram")
    assert not hasattr(eng, "compute_pnl")
    assert not hasattr(eng, "execute")


def test_reset_daily_clears_counts():
    eng = _eng()
    eng.classify(Event("paper_signal", BASE))
    eng.reset_daily()
    assert eng.daily_counts() == {}
