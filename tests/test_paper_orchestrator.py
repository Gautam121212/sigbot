"""Paper orchestrator — two-clock forward runner. Signal clock is event-driven."""
from sigbot.live_health_monitor import HealthState, LiveBehaviour
from sigbot.paper_orchestrator import (
    PaperOrchestrator, signal_set_changed)
from sigbot.risk_firewall import PortfolioState
from sigbot.strategy_adapter import (
    DeclaredClaims, NormalizedSignal, TargetPosition)


def _sig(weights, as_of="2024-06-03"):
    return NormalizedSignal("SIGBOT-INFLECTION-001", as_of,
                            [TargetPosition(s, w) for s, w in weights.items()],
                            DeclaredClaims())


def _state():
    return PortfolioState(equity=100000.0, positions={},
                          sector_of={"NVDA": "T", "CRWD": "T", "SNOW": "T"})


def _behaviour(**kw):
    base = dict(win_rate=58, signals_per_month=12, avg_position_pct=4,
                execution_drag_bps=30, current_drawdown_pct=15)
    base.update(kw)
    return LiveBehaviour(**base)


# ── signal-set-change detector ──────────────────────────────────────────────
def test_first_signal_is_a_change():
    assert signal_set_changed(None, _sig({"NVDA": 0.04}))


def test_identical_signal_set_is_not_a_change():
    a = _sig({"NVDA": 0.04, "CRWD": 0.04})
    b = _sig({"NVDA": 0.04, "CRWD": 0.04}, as_of="2024-06-04")
    assert not signal_set_changed(a, b)      # same book, different day


def test_different_symbols_is_a_change():
    a = _sig({"NVDA": 0.04, "CRWD": 0.04})
    b = _sig({"NVDA": 0.04, "SNOW": 0.04})
    assert signal_set_changed(a, b)


def test_different_weight_is_a_change():
    a = _sig({"NVDA": 0.04})
    b = _sig({"NVDA": 0.06})
    assert signal_set_changed(a, b)


# ── the two clocks ──────────────────────────────────────────────────────────
def test_signal_clock_seals_on_new_book():
    orch = PaperOrchestrator()
    n = orch.daily_signal_cycle(_sig({"NVDA": 0.04, "CRWD": 0.04}), _state(),
                                {"NVDA": 120, "CRWD": 300}, {}, "2024-06-03")
    assert n == 2


def test_signal_clock_does_not_reseal_same_fundamentals():
    """The core: a daily run with unchanged fundamentals seals NOTHING."""
    orch = PaperOrchestrator()
    orch.daily_signal_cycle(_sig({"NVDA": 0.04}), _state(),
                            {"NVDA": 120}, {}, "2024-06-03")
    n2 = orch.daily_signal_cycle(_sig({"NVDA": 0.04}, as_of="2024-06-04"),
                                 _state(), {"NVDA": 121}, {}, "2024-06-04")
    assert n2 == 0                           # no duplicate decision


def test_signal_clock_reseals_when_set_changes():
    orch = PaperOrchestrator()
    orch.daily_signal_cycle(_sig({"NVDA": 0.04, "CRWD": 0.04}), _state(),
                            {"NVDA": 120, "CRWD": 300}, {}, "2024-06-03")
    n2 = orch.daily_signal_cycle(_sig({"NVDA": 0.04, "SNOW": 0.04},
                                      as_of="2024-08-15"),
                                 _state(), {"NVDA": 130, "SNOW": 160}, {},
                                 "2024-08-15")
    assert n2 == 2                           # set changed -> reseal


def test_monitoring_clock_does_not_reseal():
    """The monitoring cycle marks and reports; it never seals a decision."""
    orch = PaperOrchestrator()
    orch.daily_signal_cycle(_sig({"NVDA": 0.04}), _state(),
                            {"NVDA": 120}, {}, "2024-06-03")
    before = len(orch.session.journal.signals())
    orch.daily_monitoring_cycle("2024-06-04", 0, _behaviour())
    assert len(orch.session.journal.signals()) == before   # unchanged


# ── live vs historical comparison ───────────────────────────────────────────
def test_report_compares_to_historical_bands():
    orch = PaperOrchestrator()
    orch.daily_signal_cycle(_sig({"NVDA": 0.04}), _state(),
                            {"NVDA": 120}, {}, "2024-06-03")
    r = orch.daily_monitoring_cycle("2024-06-03", 1, _behaviour())
    assert all("within band" in v for v in r.live_vs_historical.values())


def test_report_flags_frequency_drift():
    """Signal frequency spiking (the daily-reseal failure mode) is flagged."""
    orch = PaperOrchestrator()
    r = orch.daily_monitoring_cycle("2024-06-03", 0,
                                    _behaviour(signals_per_month=250))
    assert "DRIFTING" in r.live_vs_historical["signals_per_month"]


def test_health_quarantines_on_process_drift():
    orch = PaperOrchestrator()
    r = orch.daily_monitoring_cycle("2024-06-03", 0,
                                    _behaviour(win_rate=95, signals_per_month=60))
    assert r.health.state == HealthState.QUARANTINED


def test_normal_process_stays_healthy():
    orch = PaperOrchestrator()
    r = orch.daily_monitoring_cycle("2024-06-03", 0, _behaviour(current_drawdown_pct=20))
    assert r.health.state == HealthState.HEALTHY   # down but normal process


# ── no broker, no re-decide ─────────────────────────────────────────────────
def test_orchestrator_has_no_broker():
    orch = PaperOrchestrator()
    assert not hasattr(orch, "broker")
    assert not hasattr(orch, "submit_to_broker")
