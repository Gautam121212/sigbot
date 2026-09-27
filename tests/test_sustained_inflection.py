"""Sustained inflection — the overlooked second-derivative edge."""
from sigbot.sustained_inflection import is_tradeable, sustained_inflection


def test_dual_acceleration_fires():
    r = sustained_inflection([0.55, 0.58, 0.61, 0.64], [0.20, 0.28, 0.38])
    assert r.is_inflection and is_tradeable(r)
    assert r.strength == 5


def test_margin_up_but_revenue_fading_does_not_fire():
    """The key distinction: margin up with FADING revenue is financial
    engineering, not a real inflection — must not fire."""
    r = sustained_inflection([0.55, 0.58, 0.61, 0.64], [0.38, 0.28, 0.20])
    assert not r.is_inflection


def test_margin_not_sustained_does_not_fire():
    # margin up only 1 quarter (choppy) -> not sustained
    r = sustained_inflection([0.60, 0.55, 0.61, 0.64], [0.20, 0.28, 0.38])
    assert not r.is_inflection


def test_insufficient_history_is_safe():
    r = sustained_inflection([0.6, 0.62], [0.2])
    assert not r.is_inflection


def test_it_is_flagged_novel():
    from sigbot.novelty_check import EDGE_NOVELTY
    assert EDGE_NOVELTY["novel/sustained-inflection"][0] == "NOVEL"
