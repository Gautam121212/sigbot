"""Tests for market hours.

The proposed scheduler used `datetime.now()` — local time — to decide whether
NYSE was open. From Delhi that inverts every US decision, and the system then
reads the resulting "no data" as "no signal".
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from sigbot.market_hours import (
    HOLIDAYS, Venue, holidays_stale, is_open,
    is_open_for, next_open, should_poll, status, venue_for,
)

IST = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")


def _ist(h, m=0, d=31, mo=8):        # 2026-08-31 is a Monday
    return datetime(2026, mo, d, h, m, tzinfo=IST)


# ------------------------------------------------- the bug being fixed

@pytest.mark.parametrize("hour,us_open", [(10, False), (14, False),
                                          (20, True), (23, True), (2, False)])
def test_us_hours_are_judged_in_new_york_not_delhi(hour, us_open):
    """As-written, all four of the first cases were inverted."""
    assert is_open(Venue.NYSE, _ist(hour)) is us_open


def test_india_hours_are_judged_in_india():
    assert is_open(Venue.NSE, _ist(10)) is True
    assert is_open(Venue.NSE, _ist(16)) is False
    assert is_open(Venue.NSE, _ist(9, 0)) is False       # opens 09:15


def test_the_two_venues_disagree_at_the_same_instant():
    """The whole point: one clock cannot serve both."""
    noon_ist = _ist(12)
    assert is_open(Venue.NSE, noon_ist) and not is_open(Venue.NYSE, noon_ist)
    late = _ist(21)
    assert is_open(Venue.NYSE, late) and not is_open(Venue.NSE, late)


# ------------------------------------------------------------ calendars

def test_crypto_never_closes():
    for hour in range(0, 24, 6):
        assert is_open(Venue.CRYPTO, _ist(hour))
    assert is_open(Venue.CRYPTO, _ist(12, d=30, mo=8))   # a Sunday


def test_weekends_are_closed():
    sunday = _ist(12, d=30)
    saturday = _ist(12, d=29)
    for venue in (Venue.NSE, Venue.NYSE):
        assert not is_open(venue, sunday)
        assert not is_open(venue, saturday)


def test_holidays_are_closed():
    republic_day = datetime(2026, 1, 26, 11, tzinfo=IST)
    assert date(2026, 1, 26) in HOLIDAYS[Venue.NSE]
    assert not is_open(Venue.NSE, republic_day)

    christmas = datetime(2026, 12, 25, 11, tzinfo=NY)
    assert not is_open(Venue.NYSE, christmas)


def test_an_unknown_year_is_flagged_not_assumed_open():
    """Silently treating an unknown year as holiday-free would have the system
    polling a shut exchange and recording the silence as a market fact."""
    future = datetime(2030, 6, 1, 11, tzinfo=IST)
    assert holidays_stale(future)
    assert not holidays_stale(_ist(12))
    assert "Holiday table has run out" in status(future)


# ------------------------------------------------------------- routing

@pytest.mark.parametrize("symbol,venue", [
    ("NVDA", Venue.NYSE), ("SPY", Venue.NYSE),
    ("RELIANCE.NS", Venue.NSE), ("TCS.NS", Venue.NSE),
    ("BTC-USD", Venue.CRYPTO), ("SOL-USD", Venue.CRYPTO),
])
def test_symbols_route_to_the_right_venue(symbol, venue):
    assert venue_for(symbol) is venue


def test_is_open_for_uses_the_symbol_venue():
    noon = _ist(12)
    assert is_open_for("RELIANCE.NS", noon)
    assert not is_open_for("NVDA", noon)
    assert is_open_for("BTC-USD", noon)


# ---------------------------------------------------------- next_open

def test_next_open_is_now_when_already_open():
    noon = _ist(12)
    assert next_open(Venue.NSE, noon) == noon.astimezone(timezone.utc)


def test_next_open_skips_the_weekend():
    friday_evening = _ist(20, d=28)
    nxt = next_open(Venue.NSE, friday_evening)
    assert nxt.astimezone(IST).weekday() == 0, "should land on Monday"


def test_next_open_skips_a_holiday():
    before = datetime(2026, 1, 25, 20, tzinfo=IST)      # 26th is a holiday
    nxt = next_open(Venue.NSE, before).astimezone(IST)
    assert nxt.date() != date(2026, 1, 26)


def test_next_open_is_always_in_the_future_or_now():
    for venue in (Venue.NSE, Venue.NYSE):
        for hour in (2, 10, 14, 20, 23):
            when = _ist(hour)
            assert next_open(venue, when) >= when.astimezone(timezone.utc)


# ------------------------------------------------------------ polling

def test_should_poll_says_why_not():
    """A closed market and a failed fetch must not look the same."""
    ok, why = should_poll("RELIANCE.NS", _ist(12))
    assert ok and why == "market open"

    ok, why = should_poll("RELIANCE.NS", _ist(20))
    assert not ok and "closed" in why

    ok, why = should_poll("NVDA", _ist(12, d=30))
    assert not ok and why == "weekend"

    ok, why = should_poll("RELIANCE.NS", datetime(2026, 1, 26, 11, tzinfo=IST))
    assert not ok and "holiday" in why


def test_crypto_always_polls():
    for hour in (3, 12, 23):
        ok, _ = should_poll("BTC-USD", _ist(hour))
        assert ok


def test_status_covers_every_venue():
    text = status(_ist(12))
    for venue in Venue:
        assert venue.value in text
    assert "open" in text and "closed" in text
    assert "opens in" in text


# ------------------------------------------------------------------ WAL

def test_every_store_uses_wal(tmp_path):
    """Without WAL, a system polling several markets at once eventually returns
    'database is locked', which surfaces as a data outage rather than the
    contention it actually is."""
    import importlib
    import sqlite3

    # Only test the stores this tree actually has. Naming modules that may not
    # be installed turns a WAL check into an import error, which is how three
    # round-trips got spent chasing missing files.
    stores = [("shadow", "ShadowLedger"), ("watchlist", "Watchlist"),
              ("event_memory", "EventMemory"), ("adapt", "Adaptations"),
              ("pit_store", "PitStore"), ("patterns", "PatternRegistry")]
    checked = 0
    for module_name, class_name in stores:
        try:
            module = importlib.import_module(f"sigbot.{module_name}")
        except ImportError:
            continue
        path = tmp_path / f"{module_name}.db"
        getattr(module, class_name)(str(path))
        with sqlite3.connect(path) as con:
            mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", f"{module_name} is in {mode}, not WAL"
        checked += 1
    assert checked >= 2, "no stores found to check — the test proves nothing"


def test_wal_survives_reopening(tmp_path):
    """WAL is a property of the file, not the connection. If it did not
    persist, every reader would need to remember to set it."""
    import sqlite3

    from sigbot.shadow import ShadowLedger

    path = tmp_path / "s.db"
    ShadowLedger(str(path))
    with sqlite3.connect(path) as con:          # a plain connection, no PRAGMA
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
