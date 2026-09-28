"""8-K classifier — the hypothesis-testing engine."""
from sigbot.eight_k_classifier import (
    classify_structural, describe, hypothesis_falsified, tradeable_classes)


def test_structural_classifier_logic():
    assert classify_structural(["2.01", "1.01"], False) == "M&A"
    assert classify_structural(["1.01", "3.02"], False) == "Financing-equity"
    assert classify_structural(["1.01", "2.03"], False) == "Financing-debt"
    assert classify_structural(["1.01"], True) == "Amendment"
    assert classify_structural(["1.01"], False) == "Pure-agreement"
    assert classify_structural(["9.99"], False) == "Other"


def test_hypothesis_is_falsified_at_item_level():
    """The decisive finding: no structural class is tradeable."""
    assert hypothesis_falsified()
    assert tradeable_classes() == []


def test_describe_states_the_falsification():
    out = describe()
    assert "FALSIFIED" in out
    assert "+0.08%" in out                          # best class, still zero
