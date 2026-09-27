"""Novelty check — honest flags on whether edges are genuinely new."""
from sigbot.novelty_check import EDGE_NOVELTY, any_genuinely_novel, describe


def test_no_edge_is_genuinely_novel_and_durable():
    """The honest answer the user demanded: these are known factors."""
    assert not any_genuinely_novel()


def test_dead_edges_are_flagged():
    assert EDGE_NOVELTY["crypto/turnover"][0] == "DEAD"
    assert EDGE_NOVELTY["crypto/small-cap"][0] == "DEAD"


def test_known_factors_are_flagged_known():
    assert EDGE_NOVELTY["stocks/quality-growth"][0] == "KNOWN"


def test_describe_is_honest_about_no_secret_edge():
    out = describe()
    assert "no genuinely novel" in out
    assert "not a secret" in out
    assert "alt-data" in out
