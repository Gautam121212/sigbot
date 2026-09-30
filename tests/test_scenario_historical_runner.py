"""Historical scenario runner — frozen inputs, locked OOS, multiple-testing correction."""
import pytest

from sigbot.scenario_historical_runner import (
    ScenarioHistoricalRunner, _bonferroni_threshold)
from sigbot.scenario_intelligence import (
    ScenarioDefinition, ScenarioLibrary, ScenarioRegistry)


def _frozen_registry(n=20):
    r = ScenarioRegistry()
    for i in range(n):
        r.add(ScenarioDefinition(f"scn{i}", (("f", i, i + 1),)))
    r.freeze()
    return r


def _runner(reg, strategies=("INFLECTION-001", "MOMENTUM")):
    return ScenarioHistoricalRunner(reg, ScenarioLibrary(registry=reg),
                                    strategy_ids=strategies)


# ── control 1: frozen inputs ────────────────────────────────────────────────
def test_run_requires_frozen_registry():
    r = ScenarioRegistry()
    r.add(ScenarioDefinition("s", (("f", 0, 1),)))
    # NOT frozen
    runner = ScenarioHistoricalRunner(r, ScenarioLibrary(registry=r),
                                      strategy_ids=("A",))
    with pytest.raises(ValueError):
        runner.run(lambda sid, strat: None)


# ── control 3: multiple-testing correction ──────────────────────────────────
def test_correction_bar_rises_with_cell_count():
    assert _bonferroni_threshold(1) < _bonferroni_threshold(40)
    assert _bonferroni_threshold(40) > 3.0     # much stricter than 1.96


def test_chance_edge_fails_corrected_bar():
    """A t-stat that passes uncorrected (2.1) fails when it's 1 of 40 cells."""
    reg = _frozen_registry(20)
    runner = _runner(reg)

    def cell_data(sid, strat):
        if sid == "scn1" and strat == "MOMENTUM":
            return dict(n=40, dev_median=3.0, oos_median=2.8, control_median=1.0,
                        oos_mean=3.0, oos_std=9.0)      # t ~ 2.1
        return dict(n=100, dev_median=1.0, oos_median=1.0, control_median=1.0,
                    oos_mean=1.0, oos_std=30.0)
    runner.run(cell_data)
    # the chance edge is NOT promoted to a specialist
    assert "scn1" not in runner.specialists()


def test_strong_edge_survives_correction():
    reg = _frozen_registry(20)
    runner = _runner(reg)

    def cell_data(sid, strat):
        if sid == "scn0" and strat == "INFLECTION-001":
            return dict(n=400, dev_median=4.8, oos_median=4.5, control_median=1.7,
                        oos_mean=5.0, oos_std=20.0)     # t = 5.0
        return dict(n=100, dev_median=1.0, oos_median=1.0, control_median=1.0,
                    oos_mean=1.0, oos_std=30.0)
    runner.run(cell_data)
    assert runner.specialists().get("scn0") == "INFLECTION-001"


# ── control 2: locked OOS ───────────────────────────────────────────────────
def test_dev_only_edge_does_not_survive():
    """Edge in dev but not OOS is not a specialist."""
    reg = _frozen_registry(5)
    runner = _runner(reg)

    def cell_data(sid, strat):
        if sid == "scn0" and strat == "INFLECTION-001":
            # strong dev, but OOS median below control -> fails survives_oos
            return dict(n=400, dev_median=5.0, oos_median=0.5, control_median=1.7,
                        oos_mean=5.0, oos_std=20.0)
        return dict(n=100, dev_median=1.0, oos_median=1.0, control_median=1.0,
                    oos_mean=1.0, oos_std=30.0)
    runner.run(cell_data)
    assert "scn0" not in runner.specialists()


# ── tail dependence blocks specialist status ────────────────────────────────
def test_tail_dependent_cell_not_a_specialist():
    reg = _frozen_registry(3)
    runner = _runner(reg)

    def cell_data(sid, strat):
        if sid == "scn0" and strat == "INFLECTION-001":
            # +mean, -median (the Ideas trap), high t from the outlier
            return dict(n=400, dev_median=-1.0, oos_median=-1.0,
                        control_median=-3.0, oos_mean=8.0, oos_std=20.0)
        return dict(n=100, dev_median=1.0, oos_median=1.0, control_median=1.0,
                    oos_mean=1.0, oos_std=30.0)
    runner.run(cell_data)
    assert "scn0" not in runner.specialists()


# ── NO SPECIALIST is a valid finding ────────────────────────────────────────
def test_no_specialist_is_reported():
    reg = _frozen_registry(10)
    runner = _runner(reg)
    # nothing has edge
    runner.run(lambda sid, strat: dict(
        n=100, dev_median=1.0, oos_median=1.0, control_median=1.0,
        oos_mean=1.0, oos_std=30.0))
    assert len(runner.no_specialist_scenarios()) == 10
    assert runner.specialists() == {}


def test_report_marks_no_trade():
    reg = _frozen_registry(2)
    runner = _runner(reg)
    runner.run(lambda sid, strat: dict(
        n=50, dev_median=0.5, oos_median=0.5, control_median=1.0,
        oos_mean=0.5, oos_std=30.0))
    report = runner.report()
    assert "NO SPECIALIST" in report and "NO TRADE" in report


# ── no optimization / no reselection ────────────────────────────────────────
def test_runner_does_not_expose_optimization():
    reg = _frozen_registry(2)
    runner = _runner(reg)
    assert not hasattr(runner, "optimize")
    assert not hasattr(runner, "pick_best_cagr")
    assert not hasattr(runner, "refine_scenario")
