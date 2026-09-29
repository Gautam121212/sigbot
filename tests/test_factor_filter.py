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


def test_momentum_does_not_survive_oos():
    """The correction: momentum's in-sample edge collapsed out-of-sample."""
    from sigbot.factor_filter import OOS
    assert not OOS.momentum_survives_oos()
    assert OOS.mom_oos_median < OOS.mom_dev_median - 3.0   # large decay


def test_quality_partially_survives_oos():
    """Quality (ROIC) held a weak but real OOS edge over rejected trades."""
    from sigbot.factor_filter import OOS
    assert OOS.quality_survives_oos()


def test_no_filter_is_production_ready_yet():
    """Honest state: inflection stands alone; quality needs one more pass."""
    from sigbot.factor_filter import production_ready_filter
    verdict = production_ready_filter()
    assert "quality-only" in verdict or "none" in verdict
    assert "momentum+quality" not in verdict
