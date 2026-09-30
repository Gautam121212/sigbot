"""Scenario data pipeline — the first real SIGBOT Scenario Map."""
from sigbot.scenario_data_pipeline import (
    FIRST_SCENARIO_MAP, ScenarioMapCell, describe, edge_ranking, specialists)


def test_map_has_all_regime_scenarios():
    names = {c.scenario for c in FIRST_SCENARIO_MAP}
    assert names == {"stress", "normal", "bull"}


def test_edge_is_signal_minus_control():
    stress = next(c for c in FIRST_SCENARIO_MAP if c.scenario == "stress")
    assert stress.oos_edge == round(
        stress.oos_signal_median - stress.oos_control_median, 2)


def test_specialists_survive_oos_and_correction():
    for name in specialists():
        c = next(x for x in FIRST_SCENARIO_MAP if x.scenario == name)
        assert c.survives_oos()
        assert c.survives_correction()
        assert not c.tail_dependent


def test_edge_strongest_in_stress_and_normal_not_bull():
    """The key finding: bull has the THINNEST edge."""
    ranking = dict(edge_ranking())
    assert ranking["bull"] < ranking["stress"]
    assert ranking["bull"] < ranking["normal"]


def test_map_is_labelled_provisional_not_validated():
    for c in FIRST_SCENARIO_MAP:
        assert "PROVISIONAL" in c.verdict() or "NO SPECIALIST" in c.verdict() \
            or "REJECT" in c.verdict()
    assert "PROVISIONAL" in describe()
    assert "validated" in describe().lower()   # explicitly discusses the caveat


def test_data_quality_tag_present():
    for c in FIRST_SCENARIO_MAP:
        assert "pit" in c.data_quality.lower()


def test_tail_dependent_cell_rejected():
    tail = ScenarioMapCell("x", 100, 5, 1, -1, -3, 2.0, 5.0, 2.0,
                           tail_dependent=True)
    assert not tail.is_specialist()
    assert "REJECT" in tail.verdict()


def test_no_oos_edge_is_no_trade():
    weak = ScenarioMapCell("y", 100, 5, 1, 1, 3, -2.0, 5.0, 2.0,
                           tail_dependent=False)   # oos signal < control
    assert not weak.is_specialist()
    assert "NO TRADE" in weak.verdict()


def test_fails_correction_is_no_trade():
    low_t = ScenarioMapCell("z", 100, 5, 1, 3, 1, 2.0, 1.5, 2.4,
                            tail_dependent=False)   # t below bar
    assert not low_t.is_specialist()
    assert "correction" in low_t.verdict()


# ── multi-feature scenario map (the regime expansion) ───────────────────────
def test_multi_feature_map_exists():
    from sigbot.scenario_data_pipeline import MULTI_FEATURE_MAP
    assert len(MULTI_FEATURE_MAP) == 4


def test_tiny_samples_reported_as_insufficient():
    """The high-accel cells are too small to judge — reported, not cherry-picked."""
    from sigbot.scenario_data_pipeline import multi_feature_insufficient
    insuf = multi_feature_insufficient()
    assert "high_accel_high_reaction" in insuf
    assert "high_accel_low_reaction" in insuf


def test_high_accel_hypothesis_failed():
    """The pre-registered hypothesis failed — honest negative result retained."""
    from sigbot.scenario_data_pipeline import MULTI_FEATURE_MAP
    high = [c for c in MULTI_FEATURE_MAP if c.scenario.startswith("high_accel")]
    # every high-accel cell is either insufficient or non-positive
    for c in high:
        assert not c.sufficient_sample() or (c.oos_median is not None
                                             and c.oos_median <= 0)


def test_large_cells_are_suggestive_not_validated():
    """The price-reaction split is suggestive, explicitly NOT a validated sub-specialist."""
    from sigbot.scenario_data_pipeline import MULTI_FEATURE_MAP
    large = [c for c in MULTI_FEATURE_MAP if c.total_n >= 100]
    assert len(large) == 2
    for c in large:
        assert "not a validated sub-specialist" in c.verdict()


def test_low_reaction_beats_high_reaction_directionally():
    """The economically-sensible finding: buy before the price runs."""
    from sigbot.scenario_data_pipeline import MULTI_FEATURE_MAP
    m = {c.scenario: c for c in MULTI_FEATURE_MAP}
    low = m["mod_accel_low_reaction"]
    high = m["mod_accel_high_reaction"]
    assert low.dev_median > high.dev_median
    assert low.oos_median > high.oos_median


def test_findings_document_the_failed_hypothesis():
    from sigbot.scenario_data_pipeline import MULTI_FEATURE_FINDINGS
    joined = " ".join(MULTI_FEATURE_FINDINGS)
    assert "FAILED" in joined
    assert "SUGGESTIVE" in joined or "suggestive" in joined
