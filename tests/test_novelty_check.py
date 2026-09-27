"""Novelty check — honest flags on whether edges are genuinely new."""
from sigbot.novelty_check import EDGE_NOVELTY, any_genuinely_novel, describe


def test_one_genuinely_novel_edge_was_found():
    """After deep decomposition, sustained-inflection IS genuinely novel —
    the sustained dual margin+growth acceleration nobody systematically screens."""
    assert any_genuinely_novel()


def test_dead_edges_are_flagged():
    assert EDGE_NOVELTY["crypto/turnover"][0] == "DEAD"
    assert EDGE_NOVELTY["crypto/small-cap"][0] == "DEAD"


def test_known_factors_are_flagged_known():
    assert EDGE_NOVELTY["stocks/quality-growth"][0] == "KNOWN"


def test_describe_reports_the_novel_edge():
    out = describe()
    assert "sustained-inflection" in out
    assert "novel" in out.lower()
