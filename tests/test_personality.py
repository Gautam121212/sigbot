"""Behaviour profiles: real, persistent, and NOT a filter until tested as one."""
from __future__ import annotations

from sigbot.personality import (
    UNIVERSE_BOUNCE,
    Profile,
    profile_from_closes,
    veto,
)


def test_the_veto_is_off_because_it_tested_flat():
    """It removed 87 of 252 occurrences and moved the hit rate 57.1% -> 57.0%.
    The profile measures bounce after an ORDINARY down day; the setup fires on
    a DEEP washout. A disposition measured on one does not transfer."""
    stubborn = Profile("MARA", down_days=300, raw_bounce_pct=41.0,
                       shrunk_bounce_pct=44.0)
    assert stubborn.is_vetoed, "the profile still identifies it"
    assert veto(stubborn, "BUY") is None, "but it must not gate anything"


def test_estimates_are_shrunk_toward_the_universe():
    """Every extreme reading in the first half moved back toward the middle in
    the second. Carrying the raw rate forward overstates what comes next."""
    closes = [100.0]
    for _ in range(30):                     # 30 down days, all bouncing
        closes += [closes[-1] * 0.95, closes[-1] * 0.99]
    p = profile_from_closes("X", closes)
    assert p.raw_bounce_pct > p.shrunk_bounce_pct, "must shrink"
    assert p.shrunk_bounce_pct < 60.0, "a thin sample must stay near average"


def test_a_thin_history_lands_near_the_average():
    p = profile_from_closes("NEW", [100.0, 98.0, 99.0])
    assert abs(p.shrunk_bounce_pct - UNIVERSE_BOUNCE) < 1.0


def test_no_history_does_not_crash_or_claim_anything():
    p = profile_from_closes("EMPTY", [])
    assert p.down_days == 0
    assert "Not enough history" in p.plain()


def test_plain_english_never_leaks_statistics():
    p = Profile("AAPL", 300, 55.0, 53.0)
    text = p.plain()
    for jargon in ("shrunk", "prior", "Spearman", "mean-reversion setup"):
        assert jargon.lower() not in text.lower() or jargon == "mean-reversion setup"
