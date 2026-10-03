"""Notification pipeline — the policy is the structural gate; real-path tests."""
from datetime import datetime, timedelta, timezone

import pytest

from sigbot.notification_policy import Event, NotificationClass
from sigbot.notification_pipeline import (
    DigestSchedule, NotificationDecision, NotificationPipeline,
    TelegramSender, UnauthorizedNotification)

BASE = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)


def _pipe():
    return NotificationPipeline(
        schedule=DigestSchedule(timezone_name="Asia/Jakarta", daily_time="08:00"))


# ── the safety rule: sender only accepts sealed decisions ───────────────────
def test_sender_refuses_unsealed_decision():
    sender = TelegramSender()
    fake = NotificationDecision(NotificationClass.CRITICAL, "FAKE", "")
    with pytest.raises(UnauthorizedNotification):
        sender.deliver(fake)


def test_sender_has_no_direct_send_method():
    sender = TelegramSender()
    assert not hasattr(sender, "send")
    assert not hasattr(sender, "send_text")
    assert not hasattr(sender, "send_message")


def test_sealed_decision_from_pipeline_is_accepted():
    pipe, sender = _pipe(), TelegramSender()
    d = pipe.ingest(Event("broker_position_mismatch", BASE, affects_capital=True,
                          incident_id="INC-1"))
    assert d is not None
    sender.deliver(d)                   # accepted
    assert len(sender.sent_messages()) == 1


# ── THE REAL-PATH ACCEPTANCE TEST ───────────────────────────────────────────
def test_acceptance_24h_routine_zero_immediate():
    pipe, sender = _pipe(), TelegramSender()
    routine = ["scheduler_tick", "model_started", "model_finished",
               "prediction_created", "research_hypothesis", "research_rejected",
               "scan_success", "heartbeat", "paper_trade_normal",
               "prediction_resolved_normal", "data_refresh", "db_update"]
    for i in range(3000):
        d = pipe.ingest(Event(routine[i % len(routine)],
                              BASE + timedelta(seconds=i)))
        if d is not None:
            sender.deliver(d)
    for _ in range(300):
        pipe.ingest(Event("paper_signal", BASE))
        pipe.ingest(Event("research_generated", BASE))
    assert sender.sent_messages() == []     # zero immediate alerts


def test_acceptance_incident_one_alert_one_recovery():
    pipe, sender = _pipe(), TelegramSender()
    inc = "INC-204"
    d = pipe.ingest(Event("broker_position_mismatch", BASE, affects_capital=True,
                          incident_id=inc))
    sender.deliver(d)
    # repeats suppressed
    for i in range(10):
        r = pipe.ingest(Event("broker_position_mismatch",
                              BASE + timedelta(seconds=i + 1), incident_id=inc))
        assert r is None
    # recovery once
    rec = pipe.ingest(Event("broker_position_mismatch", BASE + timedelta(minutes=5),
                            incident_id=inc, is_recovery=True))
    sender.deliver(rec)
    assert len(sender.sent_messages()) == 2


def test_acceptance_restart_mid_incident_no_duplicate():
    pipe, sender = _pipe(), TelegramSender()
    inc = "INC-300"
    sender.deliver(pipe.ingest(Event("trading_paused", BASE, affects_capital=True,
                                     incident_id=inc)))
    snap = pipe.policy.snapshot()
    pipe2 = _pipe()
    pipe2.policy.restore(snap)
    r = pipe2.ingest(Event("trading_paused", BASE + timedelta(minutes=1),
                           incident_id=inc))
    assert r is None


# ── daily digest: once per day, owner-local, not an incident ────────────────
def test_daily_emits_once_at_local_time():
    pipe, sender = _pipe(), TelegramSender()
    before = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)   # 07:00 Jakarta
    at8 = datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)      # 08:00 Jakarta
    # before the local time -> nothing
    assert pipe.maybe_emit_daily(before, system_ok={"data": True},
                                 lifecycle_state="PAPER", capital="LOCKED",
                                 paper={}, research={}, critical_count=0) is None
    # at the local time -> emits
    d = pipe.maybe_emit_daily(at8, system_ok={"data": True},
                              lifecycle_state="PAPER", capital="LOCKED",
                              paper={}, research={}, critical_count=0)
    assert d is not None
    sender.deliver(d)
    # again same day -> nothing (no duplicate, no recursion)
    d2 = pipe.maybe_emit_daily(at8 + timedelta(hours=3), system_ok={"data": True},
                               lifecycle_state="PAPER", capital="LOCKED",
                               paper={}, research={}, critical_count=0)
    assert d2 is None


def test_daily_is_not_an_incident():
    """The daily summary must not re-enter the policy or become an incident."""
    pipe = _pipe()
    at8 = datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)
    d = pipe.maybe_emit_daily(at8, system_ok={"data": True},
                              lifecycle_state="PAPER", capital="LOCKED",
                              paper={}, research={}, critical_count=0)
    assert d.incident_id == ""          # carries no incident id
    assert pipe.policy.open_incidents() == []    # created no incident


def test_daily_folds_in_digest_counts():
    pipe = _pipe()
    for _ in range(18):
        pipe.ingest(Event("paper_signal", BASE))
    at8 = datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)
    d = pipe.maybe_emit_daily(at8, system_ok={"data": True},
                              lifecycle_state="PAPER", capital="LOCKED",
                              paper={}, research={}, critical_count=0)
    assert "18" in d.message             # the 18 accumulated signals appear
    # counts reset after emission
    assert pipe.policy.daily_counts() == {}


# ── weekly digest ───────────────────────────────────────────────────────────
def test_weekly_emits_on_configured_day():
    pipe = NotificationPipeline(schedule=DigestSchedule(
        timezone_name="UTC", weekly_day="Sunday", weekly_time="09:00"))
    # 2026-10-04 is a Sunday
    sunday9 = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)
    d = pipe.maybe_emit_weekly(sunday9, summary_text="weekly research ...")
    assert d is not None
    assert d.notification_class == NotificationClass.WEEKLY_DIGEST
    # not Sunday -> nothing
    monday = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    pipe2 = NotificationPipeline(schedule=DigestSchedule(
        timezone_name="UTC", weekly_day="Sunday", weekly_time="09:00"))
    assert pipe2.maybe_emit_weekly(monday, summary_text="x") is None


# ── timezone comes from config, not server ──────────────────────────────────
def test_schedule_uses_configured_timezone():
    sched = DigestSchedule(timezone_name="Asia/Jakarta", daily_time="08:00")
    # 01:00 UTC == 08:00 Jakarta -> due
    at8_jkt = datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)
    assert sched.is_daily_due(at8_jkt, None)
    # 23:00 UTC == 06:00 Jakarta next day -> not yet 08:00
    early = datetime(2026, 10, 3, 23, 0, tzinfo=timezone.utc)
    assert not sched.is_daily_due(early, None)


def test_bad_timezone_falls_back_to_utc():
    sched = DigestSchedule(timezone_name="Not/AZone")
    assert sched.tz().key == "UTC"


# ── ingest is the only notification source ──────────────────────────────────
def test_silent_event_produces_no_decision():
    pipe = _pipe()
    assert pipe.ingest(Event("heartbeat", BASE)) is None


def test_digest_event_produces_no_immediate_decision():
    pipe = _pipe()
    assert pipe.ingest(Event("paper_signal", BASE)) is None
