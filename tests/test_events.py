"""Event studies store reactions, not reasoning."""
from __future__ import annotations

from sigbot.events import STUDIES, describe, expected_direction, instances


def test_war_in_a_commodity_region_drives_gold_up_not_down():
    """The sentence "war, so commodities fall" sounds like analysis and has
    the direction wrong. Storing the measured reaction is what stops a model
    reasoning its way into that error under pressure."""
    assert expected_direction("war-in-commodity-region", "gold") == "UP"
    assert expected_direction("war-in-commodity-region", "silver") == "UP"
    assert expected_direction("war-in-commodity-region", "oil") == "UP"
    assert expected_direction("war-in-commodity-region", "equities") == "DOWN"


def test_an_unrecorded_pair_returns_nothing_rather_than_a_guess():
    assert expected_direction("war-in-commodity-region", "bitcoin") is None
    assert expected_direction("never-happened", "gold") is None


def test_every_study_cites_its_sources():
    for s in STUDIES:
        assert s.sources, f"{s.instance} makes claims with no source"
        assert s.lesson and s.reactions


def test_a_single_instance_is_labelled_as_one():
    """One occurrence is an anecdote with a date attached, not a rule."""
    assert instances("war-in-commodity-region") == 1
    assert "ONE instance" in describe()


def test_the_approach_is_recorded_not_just_the_event():
    """Gold also FELL on de-escalation reports the week before. The market
    priced the probability of war in both directions, so being first to the
    headline was already late."""
    war = STUDIES[0]
    assert war.priced_in_early
    assert "on the approach" in war.lesson
