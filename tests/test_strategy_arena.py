"""Strategy arena — rank by EDGE not CAGR, flag tail-dependence, lock identities."""
import pytest

from sigbot.strategy_arena import (
    ArenaResult, EntrantProfile, StrategyArena, ValidationGate)


def _profile(sid, oos="2022-01-01"):
    return EntrantProfile(sid, "US equities", "quarterly", oos)


def _result(sid, edge, cagr=15.0, median=3.0, avg=5.0, gates_pass=True):
    g = ValidationGate.PASS if gates_pass else ValidationGate.FAIL
    return ArenaResult(sid, raw_net_cagr=cagr, max_drawdown=20, sharpe=1.2,
                       sortino=1.3, win_rate=58, median_trade=median,
                       avg_trade=avg, turnover=4, execution_drag_bps=30,
                       exposure=0.9, tail_concentration=1.5,
                       matched_control_return=cagr - edge, incremental_edge=edge,
                       walk_forward=g, oos=g, monte_carlo=g,
                       cost_sensitivity=g, parameter_stability=g)


# ── ranking is by edge, not CAGR ────────────────────────────────────────────
def test_leaderboard_ranks_by_edge_not_cagr():
    a = StrategyArena()
    a.register(_profile("LOW_CAGR_HIGH_EDGE"))
    a.register(_profile("HIGH_CAGR_LOW_EDGE"))
    a.record_result(_result("LOW_CAGR_HIGH_EDGE", edge=6.0, cagr=14.0))
    a.record_result(_result("HIGH_CAGR_LOW_EDGE", edge=1.0, cagr=30.0))
    board = a.leaderboard_by_edge()
    # the higher-CAGR strategy ranks BELOW the higher-edge one
    assert board[0].strategy_id == "LOW_CAGR_HIGH_EDGE"
    assert board[0].raw_net_cagr < board[1].raw_net_cagr   # lower CAGR, higher rank


# ── tail-dependence detection (the Ideas trap) ──────────────────────────────
def test_tail_dependence_flagged():
    a = StrategyArena()
    a.register(_profile("IDEAS"))
    r = _result("IDEAS", edge=0.1, median=-3.31, avg=0.11)   # +avg, -median
    a.record_result(r)
    assert r.tail_dependent()


def test_healthy_strategy_not_tail_dependent():
    r = _result("HEALTHY", edge=4.0, median=3.7, avg=6.5)
    assert not r.tail_dependent()


# ── survival requires real edge AND gates ───────────────────────────────────
def test_survives_needs_positive_edge():
    a = StrategyArena()
    a.register(_profile("NO_EDGE"))
    a.record_result(_result("NO_EDGE", edge=-0.4, gates_pass=True))
    assert not a.results["NO_EDGE"].survives_reality()


def test_survives_needs_gates_passing():
    a = StrategyArena()
    a.register(_profile("FAILS_GATES"))
    a.record_result(_result("FAILS_GATES", edge=5.0, gates_pass=False))
    assert not a.results["FAILS_GATES"].survives_reality()


def test_real_edge_and_gates_survives():
    a = StrategyArena()
    a.register(_profile("GOOD"))
    a.record_result(_result("GOOD", edge=4.0, gates_pass=True))
    assert a.results["GOOD"].survives_reality()


def test_cagr_alone_does_not_survive():
    """A 30% CAGR with no edge and failing gates does NOT survive."""
    a = StrategyArena()
    a.register(_profile("HIGH_CAGR"))
    a.record_result(_result("HIGH_CAGR", edge=-1.0, cagr=30.0, gates_pass=False))
    assert not a.results["HIGH_CAGR"].survives_reality()


# ── anti-multiple-testing: locked identity ──────────────────────────────────
def test_cannot_relock_oos_period():
    a = StrategyArena()
    a.register(_profile("S", oos="2022-01-01"))
    with pytest.raises(ValueError):
        a.register(_profile("S", oos="2023-06-01"))   # moving goalposts


def test_same_oos_relock_allowed():
    a = StrategyArena()
    a.register(_profile("S", oos="2022-01-01"))
    a.register(_profile("S", oos="2022-01-01"))        # idempotent, fine
    assert a.entrants["S"].locked_oos_start == "2022-01-01"


def test_result_requires_registration():
    a = StrategyArena()
    with pytest.raises(ValueError):
        a.record_result(_result("UNREGISTERED", edge=5.0))


# ── survivors filter ────────────────────────────────────────────────────────
def test_survivors_filters_correctly():
    a = StrategyArena()
    a.register(_profile("REAL"))
    a.register(_profile("FAKE"))
    a.record_result(_result("REAL", edge=4.0, gates_pass=True))
    a.record_result(_result("FAKE", edge=-0.5, gates_pass=False))
    survivors = [r.strategy_id for r in a.survivors()]
    assert survivors == ["REAL"]


# ── edge report content ─────────────────────────────────────────────────────
def test_edge_report_labels_cagr_as_not_the_criterion():
    a = StrategyArena()
    a.register(_profile("S"))
    a.record_result(_result("S", edge=4.0))
    report = a.edge_report("S")
    assert "NOT the ranking criterion" in report
    assert "incremental edge" in report
    assert "future guarantee" in report
