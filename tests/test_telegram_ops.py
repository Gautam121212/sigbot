"""Telegram ops — consumes canonical state, dedup, restart-safe, read-only."""
from sigbot.telegram_ops import (
    FORBIDDEN_COMMANDS, IncidentLedger, IncidentState, OpsEvent, Severity,
    TelegramOps)


def _ops():
    return TelegramOps()


def _critical(ops, incident_id):
    return OpsEvent("reconciliation", Severity.CRITICAL, "POSITION MISMATCH",
                    "Broker and SIGBOT positions differ.",
                    "positions disagree", "trading paused", "LOCKED",
                    requires_user_action=False, incident_id=incident_id,
                    timestamp="14:32")


# ── property 1: consumes, never calculates ──────────────────────────────────
def test_no_performance_math_methods():
    ops = _ops()
    assert not hasattr(ops, "compute_pnl")
    assert not hasattr(ops, "compute_sharpe")
    assert not hasattr(ops, "compute_drawdown")
    assert not hasattr(ops, "calculate_capital")


def test_daily_summary_only_formats_given_values():
    """The daily render shows exactly what it's handed — no recomputation."""
    ops = _ops()
    msg = ops.render_daily(
        date="3 October", system_ok={"data": True, "models": True},
        lifecycle_state="PAPER_VALIDATION", capital="LOCKED",
        paper={"signals": 12, "executed": 7, "result": "+$184", "drawdown": "0.7%"},
        research={"generated": 43, "rejected": 39, "promoted": 0},
        critical_count=0)
    assert "+$184" in msg and "LOCKED" in msg and "Nothing." in msg


# ── property 2: incident dedup ──────────────────────────────────────────────
def test_critical_incident_fires_once():
    ops = _ops()
    inc = ops.ledger.next_id(2026)
    first = ops.render_event(_critical(ops, inc))
    second = ops.render_event(_critical(ops, inc))
    assert first is not None
    assert second is None                       # deduped


def test_recovery_fires_once():
    ops = _ops()
    inc = ops.ledger.next_id(2026)
    ops.render_event(_critical(ops, inc))        # open it
    r1 = ops.render_recovery(inc, "RESOLVED", "ok", "LOCKED")
    r2 = ops.render_recovery(inc, "RESOLVED", "ok", "LOCKED")
    assert r1 is not None and r2 is None


def test_recovery_without_open_incident_sends_nothing():
    ops = _ops()
    assert ops.render_recovery("INC-2026-999999", "x", "y", "LOCKED") is None


def test_two_distinct_incidents_both_alert():
    ops = _ops()
    a, b = ops.ledger.next_id(2026), ops.ledger.next_id(2026)
    assert ops.render_event(_critical(ops, a)) is not None
    assert ops.render_event(_critical(ops, b)) is not None


def test_incident_ids_unique():
    led = IncidentLedger()
    assert led.next_id(2026) != led.next_id(2026)


# ── property 2b: restart safety ─────────────────────────────────────────────
def test_restart_does_not_realert_open_incident():
    ops1 = _ops()
    inc = ops1.ledger.next_id(2026)
    ops1.render_event(_critical(ops1, inc))      # open
    persisted = ops1.ledger.snapshot()
    # service restarts
    ops2 = _ops()
    ops2.ledger.restore(persisted)
    # the same incident firing after restart must NOT alert again
    assert ops2.render_event(_critical(ops2, inc)) is None


def test_restart_preserves_open_incident_list():
    led = IncidentLedger()
    inc = led.next_id(2026)
    led.should_alert_open(inc)
    snap = led.snapshot()
    led2 = IncidentLedger()
    led2.restore(snap)
    assert inc in led2.open_incidents()


def test_recovered_incident_not_reopened_on_restart():
    led = IncidentLedger()
    inc = led.next_id(2026)
    led.should_alert_open(inc)
    led.should_alert_recovery(inc)
    led2 = IncidentLedger()
    led2.restore(led.snapshot())
    assert inc not in led2.open_incidents()


# ── property 3: read-only, no trading commands ──────────────────────────────
def test_no_trading_command_methods():
    ops = _ops()
    for cmd in FORBIDDEN_COMMANDS:
        name = cmd.strip("/")
        assert not hasattr(ops, name), f"{cmd} must not exist"
    assert not hasattr(ops, "cmd_buy")
    assert not hasattr(ops, "cmd_go_live")
    assert not hasattr(ops, "activate_capital")


def test_read_only_commands_exist():
    ops = _ops()
    assert hasattr(ops, "cmd_status")
    assert hasattr(ops, "cmd_evidence")


# ── property 4: zero-state awareness ────────────────────────────────────────
def test_live_activation_shows_zero_state():
    ops = _ops()
    msg = ops.render_live_activation(model="INFLECTION-002",
                                     activated_at="2027-01-01", capital="AUTHORIZED")
    assert "0 days" in msg and "0 trades" in msg and "$0 P&L" in msg
    assert "NOT included" in msg                 # history separated


def test_evidence_command_reports_no_live():
    ops = _ops()
    msg = ops.cmd_evidence(has_backtest=True, has_oos=True, has_provisional=True,
                           has_paper=False, has_live=False, capital="LOCKED")
    assert "No qualifying figures yet" in msg
    assert "Live: None" in msg


# ── plain-english: no raw exceptions ────────────────────────────────────────
def test_event_renders_plain_english_not_exception():
    ops = _ops()
    inc = ops.ledger.next_id(2026)
    msg = ops.render_event(_critical(ops, inc))
    assert "Error" not in msg and "!=" not in msg
    assert "Broker and SIGBOT positions differ" in msg


# ── full event-flow lifecycle ───────────────────────────────────────────────
def test_full_incident_lifecycle():
    """NORMAL -> CRITICAL -> (dedup) -> RECOVERED, each step once."""
    ops = _ops()
    inc = ops.ledger.next_id(2026)
    # critical fires
    assert ops.render_event(_critical(ops, inc)) is not None
    assert ops.ledger._state[inc] == IncidentState.OPEN
    # dedup
    assert ops.render_event(_critical(ops, inc)) is None
    # recovery once
    assert ops.render_recovery(inc, "RESOLVED", "ok", "LOCKED") is not None
    assert ops.ledger._state[inc] == IncidentState.RECOVERED
    # no open incidents remain
    assert ops.ledger.open_incidents() == []
