"""Every professional rule was tested before it was adopted."""
from __future__ import annotations

from sigbot.professional import ADOPTED, BEHAVIOURS, REJECTED, UNTESTED, summary


def test_every_rule_carries_the_measurement_that_decided_it():
    for b in BEHAVIOURS:
        assert b.evidence and len(b.evidence) > 40, (
            f"{b.situation!r} was decided without evidence")
        assert b.verdict in (ADOPTED, REJECTED, UNTESTED)


def test_the_rejected_rules_are_recorded_not_deleted():
    """Half the textbook rules inverted on this setup. Recording them is what
    stops someone re-adding "only go long above the 200-day" in six months."""
    rejected = {b.situation for b in BEHAVIOURS if b.verdict == REJECTED}
    assert "The broad market is falling" in rejected
    assert "An earnings report is due during the hold" in rejected
    assert "Volatility explodes" in rejected


def test_nothing_live_is_left_untested():
    """The streak pause was live and untested; testing it turned out to be
    the most important result of the comparison."""
    assert not [b for b in BEHAVIOURS if b.verdict == UNTESTED]


def test_the_summary_quotes_the_edge_in_R_not_percent():
    """Percent per trade flatters a risk-sized system. What reaches the
    account is R."""
    text = summary()
    assert "+0.042 R" in text
    assert "+0.241 R" in text


def test_rejected_rules_are_actually_switched_off_in_code():
    """A rule marked REJECTED here must not be quietly active elsewhere."""
    from sigbot.scan import REGIME_FILTER

    assert REGIME_FILTER is False


def test_the_streak_pause_matches_its_recorded_evidence():
    from sigbot.risk import LOSS_STREAK_PAUSE

    assert LOSS_STREAK_PAUSE == 4, "the evidence was measured at four"
