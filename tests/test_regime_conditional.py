"""Regime-conditional expectancy — the validated stress-outperformance edge."""
from sigbot.regime_conditional import (
    REGIMES, classify_regime, describe, size_multiplier,
    stress_effect_survives_oos)


def test_stress_outperforms_bull():
    """The core finding: inflection is far stronger in stress than bull."""
    assert REGIMES["STRESS"].median_pct > REGIMES["BULL"].median_pct * 3


def test_stress_effect_survives_oos():
    """Unlike momentum/factor-filter, this holds out-of-sample."""
    assert stress_effect_survives_oos()


def test_sizing_rule_inverts_naive_derisking():
    """Size UP in stress, DOWN in bull — the counterintuitive validated rule."""
    assert size_multiplier("STRESS") > 1.0
    assert size_multiplier("BULL") < 1.0
    assert size_multiplier("NORMAL") == 1.0


def test_regime_classifier_is_point_in_time():
    assert classify_regime(-0.08, 0.01) == "STRESS"
    assert classify_regime(0.10, 0.01) == "BULL"
    assert classify_regime(0.0, 0.02) == "HIGH-VOL"
    assert classify_regime(0.0, 0.01) == "NORMAL"


def test_describe_states_the_differentiated_edge():
    out = describe()
    assert "size UP in stress" in out
    assert "4x stronger" in out


def test_stress_effect_is_not_purely_one_crisis():
    """Decomposition: real across 2019/2022/2025, not only COVID."""
    from sigbot.regime_conditional import stress_effect_is_one_crisis_artifact
    assert not stress_effect_is_one_crisis_artifact()


def test_headline_stress_median_was_covid_inflated():
    """Honest correction: robust ex-COVID median is ~half the headline."""
    from sigbot.regime_conditional import (
        STRESS_MEDIAN_ROBUST, STRESS_MEDIAN_HEADLINE)
    assert STRESS_MEDIAN_ROBUST < STRESS_MEDIAN_HEADLINE * 0.6


def test_multipliers_are_tempered_not_aggressive():
    """Stress can lose (2022-Q4/2023-Q4), so no 2.0x lever."""
    from sigbot.regime_conditional import size_multiplier, stress_can_lose
    assert stress_can_lose()
    assert size_multiplier("STRESS") <= 1.5      # tempered, not 2.0
    assert size_multiplier("STRESS") > 1.0       # but still a real tilt
