"""Paper trading — point-in-time sealed forward simulation, no broker."""
import json

from sigbot.live_health_monitor import HealthState, LiveBehaviour
from sigbot.paper_trading import (
    PaperJournal, PaperOutcome, PaperSignal, PaperTradingSession)
from sigbot.risk_firewall import PortfolioState
from sigbot.strategy_adapter import (
    DeclaredClaims, NormalizedSignal, TargetPosition)


def _signal(weights):
    return NormalizedSignal("SIGBOT-INFLECTION-001", "2024-06-03",
                            [TargetPosition(s, w) for s, w in weights.items()],
                            DeclaredClaims())


def _state():
    return PortfolioState(equity=100000.0, positions={},
                          sector_of={"NVDA": "T", "CRWD": "T"})


# ── 1. point-in-time sealing: signal has NO outcome field ───────────────────
def test_paper_signal_has_no_outcome_field():
    sess = PaperTradingSession()
    sealed = sess.record_signals(_signal({"NVDA": 0.04}), _state(),
                                 {"NVDA": 120.0}, {}, "2024-06-03")
    assert not hasattr(sealed[0], "hypothetical_pnl")
    assert not hasattr(sealed[0], "actual_price_later")


def test_outcome_is_separate_record():
    """Decision and outcome are separate record types — a future price cannot
    reach into the sealed decision."""
    assert "actual_price_later" not in PaperSignal.__dataclass_fields__
    assert "as_of" not in PaperOutcome.__dataclass_fields__


# ── 2. broker submission structurally impossible ────────────────────────────
def test_no_broker_handle():
    sess = PaperTradingSession()
    assert not hasattr(sess, "broker")
    assert not hasattr(sess, "submit_to_broker")
    assert not hasattr(sess, "place_order")


# ── 3. decision then outcome flow ───────────────────────────────────────────
def test_record_then_resolve():
    sess = PaperTradingSession()
    sess.record_signals(_signal({"NVDA": 0.04}), _state(), {"NVDA": 100.0},
                        {"NVDA": "inflection"}, "2024-06-03")
    assert len(sess.journal.unresolved()) == 1
    resolved = sess.resolve_outcomes({"NVDA": 110.0}, "2024-07-03")
    assert len(resolved) == 1
    assert resolved[0].hypothetical_pnl > 0
    assert len(sess.journal.unresolved()) == 0


def test_reason_is_sealed_with_signal():
    sess = PaperTradingSession()
    sealed = sess.record_signals(_signal({"NVDA": 0.04}), _state(),
                                 {"NVDA": 100.0},
                                 {"NVDA": "margin up 3q"}, "2024-06-03")
    assert sealed[0].reason == "margin up 3q"


# ── 4. idempotent resolution (no double-booking) ────────────────────────────
def test_resolution_is_idempotent():
    sess = PaperTradingSession()
    sess.record_signals(_signal({"NVDA": 0.04}), _state(), {"NVDA": 100.0},
                        {}, "2024-06-03")
    sess.resolve_outcomes({"NVDA": 110.0}, "2024-07-03")
    again = sess.resolve_outcomes({"NVDA": 110.0}, "2024-07-03")
    assert len(again) == 0                         # already resolved
    assert len(sess.journal.outcomes()) == 1


# ── 5. persistence survives restart ─────────────────────────────────────────
def test_journal_persists_to_disk(tmp_path):
    path = tmp_path / "paper.jsonl"
    j = PaperJournal(path)
    j.append_signal(PaperSignal("2024-06-03", "S", "NVDA", "r", 0.04, 100.0,
                                100.05, True, 4000.0, (), "sid1"))
    j.append_outcome(PaperOutcome("sid1", "2024-07-03", 110.0, 400.0, 9.9))
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "signal"
    assert json.loads(lines[1])["kind"] == "outcome"


def test_outcome_journal_is_append_only_idempotent():
    j = PaperJournal()
    o = PaperOutcome("sid1", "2024-07-03", 110.0, 400.0, 9.9)
    assert j.append_outcome(o) is True
    assert j.append_outcome(o) is False            # same signal_id ignored
    assert len(j.outcomes()) == 1


# ── 6. rejected signals never resolve into P&L ──────────────────────────────
def test_rejected_signal_not_in_unresolved():
    from sigbot.broker_reconciliation import SystemState
    from sigbot.shadow_trading import ShadowSession
    sess = PaperTradingSession(
        shadow=ShadowSession(system_state=SystemState.TRADING_PAUSED))
    sess.record_signals(_signal({"NVDA": 0.04}), _state(), {"NVDA": 100.0},
                        {}, "2024-06-03")
    # paused -> not approved -> not in the unresolved (tradeable) set
    assert len(sess.journal.unresolved()) == 0


# ── 7. health check on accrued behaviour ────────────────────────────────────
def test_health_check_flags_drift():
    sess = PaperTradingSession()
    report = sess.health_check(LiveBehaviour(win_rate=95, signals_per_month=60,
                                             avg_position_pct=4,
                                             execution_drag_bps=30,
                                             current_drawdown_pct=0))
    assert report.state == HealthState.QUARANTINED


def test_health_check_normal_is_healthy():
    sess = PaperTradingSession()
    report = sess.health_check(LiveBehaviour(win_rate=58, signals_per_month=12,
                                             avg_position_pct=4,
                                             execution_drag_bps=30,
                                             current_drawdown_pct=15))
    assert report.state == HealthState.HEALTHY


# ── 8. track record ─────────────────────────────────────────────────────────
def test_track_record_accrues():
    sess = PaperTradingSession()
    sess.record_signals(_signal({"NVDA": 0.04, "CRWD": 0.04}), _state(),
                        {"NVDA": 100.0, "CRWD": 100.0}, {}, "2024-06-03")
    sess.resolve_outcomes({"NVDA": 110.0, "CRWD": 95.0}, "2024-07-03")
    tr = sess.track_record()
    assert tr["outcomes_resolved"] == 2
    assert tr["signals_recorded"] == 2
    assert 0 <= tr["win_rate"] <= 100
