"""Tests for the event precedent store.

Two of these exist because the proposed design would have built the bias this
project prevents, inside the memory that feeds it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sigbot.event_memory import (
    MIN_PRECEDENTS, SIMILARITY_FLOOR, STRONG_FLOOR, Event, EventMemory,
)

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _ev(days_ago: int, headline: str, r3: float | None = 0.02,
        precision: str = "day", asset: str = "TSLA",
        etype: str = "product_launch") -> Event:
    return Event(asset=asset, event_date=(NOW - timedelta(days=days_ago)).date().isoformat(),
                 headline=headline, event_type=etype, source="reuters",
                 date_precision=precision, return_1d=r3, return_3d=r3, return_5d=r3)


@pytest.fixture
def mem(tmp_path):
    return EventMemory(tmp_path / "e.db")


# ------------------------------------------------- the admission question

def test_quiet_events_are_stored_too(mem):
    """Admitting only events that moved makes every later base rate a lie.

    The proposed filter (|3-day return| > 3%) dropped 224 of 300 simulated
    events. The survivors all moved by construction, so 'launches move the
    stock' would be true of the database and false of the world.
    """
    assert mem.record(_ev(400, "Tesla unveils new Model Y", r3=0.0001))
    assert mem.record(_ev(300, "Tesla unveils Cybertruck", r3=0.09))
    assert mem.count() == 2, "a quiet event was discarded"


def test_a_quiet_precedent_lowers_the_rate(mem):
    """The point of keeping quiet events: they change the answer."""
    # Both batches must use the same wording, or the second never matches the
    # query and the test proves nothing.
    for i in range(6):
        mem.record(_ev(100 + i * 30, f"Tesla unveils model refresh {i}", r3=0.05))
    query = "Tesla unveils model refresh today"
    strong = mem.recurrence("TSLA", query)
    assert strong.n_precedents == 6 and strong.up_rate == 1.0

    for i in range(6):
        mem.record(_ev(400 + i * 30, f"Tesla unveils model refresh v{i}", r3=-0.02))
    weaker = mem.recurrence("TSLA", query)
    assert weaker.n_precedents == 12
    assert weaker.up_rate < strong.up_rate, "quiet precedents did not move the rate"


def test_duplicates_are_ignored(mem):
    e = _ev(100, "Tesla unveils Model Y")
    assert mem.record(e) and not mem.record(e)
    assert mem.count() == 1


# ------------------------------------------------- the date question

def test_imprecise_dates_are_kept_but_never_counted(mem):
    """A year-only date scored against 1 January is not noise, it is wrong.

    The proposal defaulted such dates to Jan 1 and measured the reaction there,
    attributing a November event to the first trading days of January.
    """
    for i in range(8):
        mem.record(_ev(200 + i * 40, f"Tesla unveils product number {i}",
                       r3=0.05, precision="year"))
    r = mem.recurrence("TSLA", "Tesla unveils a new product")
    assert r.n_precedents == 0 and r.n_excluded == 8
    assert r.verdict == "NO PATTERN"
    assert "imprecise dates" in r.render()


def test_countable_requires_a_measured_return(mem):
    assert not _ev(10, "x", r3=None).countable
    assert not _ev(10, "x", r3=0.02, precision="month").countable
    assert _ev(10, "x", r3=0.02).countable


def test_future_dated_rows_are_not_precedents(mem):
    mem.record(Event("TSLA", (NOW + timedelta(days=30)).date().isoformat(),
                     "Tesla unveils something", "product_launch", "x",
                     return_3d=0.05))
    assert mem.precedents("TSLA", "Tesla unveils something", on=NOW) == []


# ------------------------------------------------------------- matching

def test_similar_headlines_match_and_different_ones_do_not(mem):
    mem.record(_ev(100, "Tesla unveils Model Y refresh with longer range"))
    mem.record(_ev(200, "Tesla recalls thousands of vehicles over brakes"))
    found = mem.precedents("TSLA", "Tesla unveils Model Y refresh with more range",
                           on=NOW)
    assert len(found) == 1
    assert "unveils" in found[0].event.headline
    assert found[0].similarity >= SIMILARITY_FLOOR


def test_matching_is_scoped_to_the_asset(mem):
    mem.record(_ev(100, "Tesla unveils Model Y refresh"))
    mem.record(_ev(100, "Tesla unveils Model Y refresh", asset="RIVN"))
    assert len(mem.precedents("TSLA", "Tesla unveils Model Y refresh", on=NOW)) == 1


def test_recent_precedents_outrank_older_identical_ones(mem):
    mem.record(_ev(30, "Tesla unveils Model Y refresh"))
    mem.record(_ev(2000, "Tesla unveils Model Y refresh again"))
    found = mem.precedents("TSLA", "Tesla unveils Model Y refresh", on=NOW)
    assert found[0].age_days < found[-1].age_days


# ------------------------------------------------------------- scoring

def test_nothing_is_reported_below_the_minimum(mem):
    for i in range(MIN_PRECEDENTS - 1):
        mem.record(_ev(100 + i * 30, f"Tesla unveils product number {i}", r3=0.05))
    r = mem.recurrence("TSLA", "Tesla unveils a product")
    assert r.verdict == "NO PATTERN" and r.up_rate is None
    assert f"Below {MIN_PRECEDENTS}" in r.render()


def test_the_verdict_reads_the_lower_bound_not_the_observed_rate(mem):
    """Six of seven is 86% and a lower bound of 47%. Reporting the first
    without the second is the whole problem."""
    for i in range(6):
        mem.record(_ev(100 + i * 30, f"Tesla unveils product number {i}", r3=0.05))
    mem.record(_ev(500, "Tesla unveils product number six", r3=-0.06))
    r = mem.recurrence("TSLA", "Tesla unveils a product")
    assert r.n_precedents == 7
    assert r.up_rate == pytest.approx(6 / 7, abs=0.01)
    assert r.lower < STRONG_FLOOR, "an 86% observed rate on n=7 is not STRONG"
    assert r.verdict in ("WEAK", "NO PATTERN")


def test_a_thick_consistent_record_reaches_strong(mem):
    for i in range(20):
        mem.record(_ev(100 + i * 30, f"Tesla unveils product variant {i}", r3=0.04))
    r = mem.recurrence("TSLA", "Tesla unveils a product variant")
    assert r.verdict == "STRONG" and r.lower >= STRONG_FLOOR


def test_the_render_shows_dates_and_refuses_to_forecast(mem):
    for i in range(8):
        mem.record(_ev(100 + i * 40, f"Tesla unveils product number {i}", r3=0.03))
    text = mem.recurrence("TSLA", "Tesla unveils a product").render()
    assert "dates:" in text and "median 3-day move" in text
    assert "not a forecast" in text and "caused the move" in text


def test_median_is_reported_not_mean(mem):
    """One outlier should not set the headline number."""
    for i in range(6):
        mem.record(_ev(100 + i * 30, f"Tesla unveils product number {i}", r3=0.01))
    mem.record(_ev(500, "Tesla unveils product number six", r3=0.90))
    r = mem.recurrence("TSLA", "Tesla unveils a product")
    assert r.median_3d < 0.05, "an outlier moved the reported centre"


def test_summary_is_honest_when_empty(mem):
    assert "empty" in mem.summary()
    mem.record(_ev(100, "Tesla unveils something", precision="year"))
    s = mem.summary()
    assert "1 events recorded, 0 countable" in s and "excluded" in s


def test_the_similarity_floor_is_calibrated():
    """Too strict and the store never fires; too loose and it pools unrelated
    events into a precedent count the Wilson bound then trusts."""
    from sigbot.providers.news import jaccard, tokens

    same = [("Tesla unveils new Model Y refresh",
             "Tesla unveils Model Y refresh with longer range"),
            ("Nvidia beats earnings estimates",
             "Nvidia earnings beat estimates on AI demand")]
    different = [("Tesla unveils Model Y refresh",
                  "Tesla recalls vehicles over brake fault"),
                 ("Nvidia beats earnings estimates",
                  "Nvidia faces export restrictions in China")]

    for a, b in same:
        assert jaccard(tokens(a), tokens(b)) >= SIMILARITY_FLOOR, f"{a!r} / {b!r}"
    for a, b in different:
        assert jaccard(tokens(a), tokens(b)) < SIMILARITY_FLOOR, f"{a!r} / {b!r}"


def test_loosely_worded_matches_are_rejected_and_that_is_intended(mem):
    """Documented cost of the floor: same kind of event, different wording,
    no match. Better than pooling non-precedents into the count."""
    from sigbot.providers.news import jaccard, tokens

    assert jaccard(tokens("Tesla to unveil robotaxi next month"),
                   tokens("Tesla unveils product at event")) < SIMILARITY_FLOOR


def test_the_store_knows_which_assets_it_can_serve(mem):
    """History depth, not the asset, is often why a store says nothing."""
    import numpy as np
    import pandas as pd

    def bars(years):
        idx = pd.bdate_range(end="2026-08-28", periods=int(years * 252))
        c = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, len(idx))))
        return pd.DataFrame(dict(open=c, high=c * 1.01, low=c * 0.99, close=c,
                                 volume=np.full(len(idx), 1e6)), index=idx)

    frames = {"AAPL": bars(20), "SOL-USD": bars(6), "TIA-USD": bars(1)}
    eligible = mem.eligible_assets(frames)
    assert "AAPL" in eligible and "SOL-USD" in eligible
    assert "TIA-USD" not in eligible, "a one-year asset cannot supply precedents"
