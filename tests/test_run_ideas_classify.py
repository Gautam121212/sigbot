"""8-K full-text research pipeline."""
from sigbot.run_ideas_classify import (
    Filing, classify, run_ideas_classify, subclassify_pure_agreement)


def test_full_text_subclassifier():
    assert subclassify_pure_agreement("entered a supply agreement") == "commercial"
    assert subclassify_pure_agreement("awarded a u.s. government contract") == "government"
    assert subclassify_pure_agreement("formed a joint venture") == "strategic"


def test_classify_uses_structural_then_fulltext():
    f = Filing("x", "ABC", "2020-01-01", ["1.01"], False,
               body_text="entered a supply agreement with a major customer")
    assert classify(f) == "Pure-agreement/commercial"


def test_classify_falls_back_without_body():
    f = Filing("x", "ABC", "2020-01-01", ["1.01", "3.02"], False)
    assert classify(f) == "Financing-equity"        # structural, no text needed


def test_research_run_reports_falsification():
    assert "FALSIFIED" in run_ideas_classify()
