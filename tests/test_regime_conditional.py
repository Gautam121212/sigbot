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
