"""Factor filter — the cross-sectional ML feasibility result."""
from sigbot.factor_filter import (
    RESULT, describe, factor_filter_score, passes_quality_gate)


def test_standalone_ranker_fails_to_beat_inflection():
    """The cross-sectional composite does NOT beat inflection standalone."""
    assert not RESULT.standalone_beats_inflection()
    assert RESULT.standalone_top_decile_median < RESULT.inflection_benchmark_median


def test_filter_improves_inflection():
    """But as a quality gate on inflection, it adds real median uplift."""
    assert RESULT.filter_improves_inflection()
    assert RESULT.median_uplift() > 3.0


def test_quality_gate_logic():
    assert passes_quality_gate(1.2, 0.3)            # above-average factors pass
    assert not passes_quality_gate(-0.5, -0.2)      # below-average fail
    assert factor_filter_score(1.0, 1.0) == 2.0


def test_describe_states_filter_not_engine():
    out = describe()
    assert "build the FILTER, not the discovery engine" in out
    assert "1-for-5" in out
