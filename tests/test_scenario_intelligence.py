"""Scenario intelligence — leakage-proof by construction (both leaks)."""
import pytest

from sigbot.scenario_intelligence import (
    DefinitionsFrozenError, Feature, ScenarioDefinition, ScenarioLibrary,
    ScenarioOccurrence, ScenarioOutcome, ScenarioRegistry)


def _reg():
    r = ScenarioRegistry()
    r.add(ScenarioDefinition("accel_highvol",
                             (("rev_accel", 15, 100), ("mkt_vol", 0.015, 1.0))))
    r.add(ScenarioDefinition("accel_calm",
                             (("rev_accel", 15, 100), ("mkt_vol", 0.0, 0.015))))
    return r


# ── leak 2: outcome-conditioned definition (the dangerous one) ──────────────
def test_cannot_add_scenario_after_freeze():
    r = _reg()
    r.freeze()
    with pytest.raises(DefinitionsFrozenError):
        r.add(ScenarioDefinition("cherry", (("rev_accel", 22, 24),)))


def test_cannot_attach_outcome_before_freeze():
    r = _reg()
    lib = ScenarioLibrary(registry=r)   # NOT frozen
    with pytest.raises(DefinitionsFrozenError):
        lib.attach_outcome(ScenarioOutcome("o1", "2020-01-01", 1, 1, 1, 1))


def test_freeze_hash_is_deterministic():
    h1 = _reg().freeze()
    h2 = _reg().freeze()
    assert h1 == h2                     # same definitions -> same hash


def test_freeze_hash_changes_with_definitions():
    r1 = _reg()
    r2 = _reg()
    r2.add(ScenarioDefinition("extra", (("x", 0, 1),)))
    assert r1.freeze() != r2.freeze()


# ── leak 1: feature look-ahead ──────────────────────────────────────────────
def test_occurrence_has_no_outcome_field():
    occ = ScenarioOccurrence("o1", "2020-05-01", "NVDA", ("accel_highvol",),
                             (Feature("rev_accel", 23, "%"),))
    assert not hasattr(occ, "ret_63d")
    assert not hasattr(occ, "outcome")


def test_outcome_is_separate_record():
    assert "ret_63d" not in ScenarioOccurrence.__dataclass_fields__
    assert "as_of" not in ScenarioOutcome.__dataclass_fields__


# ── magnitude, not yes/no ───────────────────────────────────────────────────
def test_features_carry_magnitude():
    f = Feature("rev_accel", 23.0, "%")
    assert f.value == 23.0             # a number, not a boolean


def test_classify_uses_magnitude_bounds():
    r = _reg()
    r.freeze()
    # rev_accel 23 + high vol -> highvol scenario, not calm
    assert r.classify({"rev_accel": 23, "mkt_vol": 0.02}) == ["accel_highvol"]
    assert r.classify({"rev_accel": 23, "mkt_vol": 0.005}) == ["accel_calm"]
    # small acceleration doesn't match at all
    assert r.classify({"rev_accel": 5, "mkt_vol": 0.02}) == []


# ── match fraction (the "87% of scenario" use case) ─────────────────────────
def test_match_fraction():
    r = _reg()
    d = r.definition("accel_highvol")
    assert d.match_fraction({"rev_accel": 20, "mkt_vol": 0.02}) == 1.0
    assert d.match_fraction({"rev_accel": 20}) == 0.5   # one of two features


# ── the conditional distribution ────────────────────────────────────────────
def test_scenario_summary_computes_conditional_distribution():
    r = _reg()
    r.freeze()
    lib = ScenarioLibrary(registry=r)
    for i, ret in enumerate([10.0, -5.0, 20.0, 8.0]):
        oid = f"o{i}"
        lib.record_occurrence(ScenarioOccurrence(
            oid, "2020-05-01", "X", ("accel_highvol",),
            (Feature("rev_accel", 20), Feature("mkt_vol", 0.02))))
        lib.attach_outcome(ScenarioOutcome(oid, "2020-08-01", 0, 0, ret, 0))
    s = lib.scenario_summary("accel_highvol")
    assert s["n"] == 4
    assert s["win_rate"] == 75.0


def test_tail_dependence_flagged_in_scenario():
    """The Ideas lesson carried in: +mean but -median = tail-dependent."""
    r = _reg()
    r.freeze()
    lib = ScenarioLibrary(registry=r)
    # returns: mostly small losses, one huge winner -> +mean, -median
    for i, ret in enumerate([-3.0, -3.0, -3.0, 200.0]):
        oid = f"o{i}"
        lib.record_occurrence(ScenarioOccurrence(
            oid, "2020-05-01", "X", ("accel_highvol",),
            (Feature("rev_accel", 20), Feature("mkt_vol", 0.02))))
        lib.attach_outcome(ScenarioOutcome(oid, "2020-08-01", 0, 0, ret, 0))
    s = lib.scenario_summary("accel_highvol")
    assert s["tail_dependent"] == 1.0
