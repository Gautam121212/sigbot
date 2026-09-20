"""Market hours — is this exchange open right now, and when next?

The proposed `scheduler.py` decided this with `datetime.now()`, which is local
time. Run from Delhi, every US decision inverts:

    IST clock   scheduler says   NYSE actually
    10:00       open             closed
    14:00       open             closed
    20:00       closed           open
    23:00       closed           open

So it would poll NYSE at 09:30–16:00 IST — 23:00–05:30 in New York — and skip
the real session. That is worse than having no scheduler, because by the same
document's warning the system then reads "no data" as "no signal", and files a
timezone bug as a market observation.

Honest constraint: holidays are hardcoded per year and go stale. `holidays_stale`
says when the table runs out rather than silently treating an unknown year as
having no holidays, which would have the system polling a closed exchange and
recording the resulting silence as a fact about the market.

Largest risk: that "closed" and "no data" get conflated anyway further
downstream. This module answers only whether the exchange is open. Whether the
caller distinguishes a closed market from a failed fetch is the caller's
problem, and `skips.py` is where that lives.

Test gap: half-days — Thanksgiving Friday, Diwali Muhurat trading — are treated
as normal sessions. Their bars exist but are thin, and nothing here flags that.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo


class Venue(str, Enum):
    NSE = "NSE"          # India
    NYSE = "NYSE"        # United States
    CRYPTO = "CRYPTO"    # never closes


@dataclass(frozen=True)
class Session:
    venue: Venue
    tz: str
    opens: time
    closes: time
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)


SESSIONS = {
    Venue.NSE: Session(Venue.NSE, "Asia/Kolkata", time(9, 15), time(15, 30)),
    Venue.NYSE: Session(Venue.NYSE, "America/New_York", time(9, 30), time(16, 0)),
    Venue.CRYPTO: Session(Venue.CRYPTO, "UTC", time(0, 0), time(23, 59),
                          weekdays=(0, 1, 2, 3, 4, 5, 6)),
}

# Full-day closures. Deliberately explicit and deliberately finite: an empty set
# for an unknown year would mean "no holidays", and the system would poll a shut
# exchange and record the silence as a market fact.
HOLIDAYS: dict[Venue, set[date]] = {
    Venue.NYSE: {
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
        date(2026, 11, 26), date(2026, 12, 25),
    },
    Venue.NSE: {
        date(2026, 1, 26), date(2026, 3, 3), date(2026, 3, 21), date(2026, 4, 1),
        date(2026, 4, 3), date(2026, 4, 14), date(2026, 5, 1), date(2026, 8, 15),
        date(2026, 10, 2), date(2026, 11, 10), date(2026, 12, 25),
    },
    Venue.CRYPTO: set(),
}

HOLIDAYS_KNOWN_THROUGH = date(2026, 12, 31)


def venue_for(symbol: str) -> Venue:
    """Which exchange a ledger symbol trades on."""
    if symbol.endswith(("-USD", "USDT")):
        return Venue.CRYPTO
    if symbol.endswith((".NS", ".BO")):
        return Venue.NSE
    return Venue.NYSE


def _local(venue: Venue, when: datetime | None = None) -> datetime:
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(ZoneInfo(SESSIONS[venue].tz))


def holidays_stale(when: datetime | None = None) -> bool:
    """True once the holiday table no longer covers the date being asked about."""
    return _local(Venue.NYSE, when).date() > HOLIDAYS_KNOWN_THROUGH


def is_open(venue: Venue | str, when: datetime | None = None) -> bool:
    """Whether the venue is trading. Always in the venue's own timezone."""
    venue = Venue(venue)
    session = SESSIONS[venue]
    if venue is Venue.CRYPTO:
        return True
    local = _local(venue, when)
    if local.weekday() not in session.weekdays:
        return False
    if local.date() in HOLIDAYS.get(venue, set()):
        return False
    return session.opens <= local.time() <= session.closes


def is_open_for(symbol: str, when: datetime | None = None) -> bool:
    return is_open(venue_for(symbol), when)


def next_open(venue: Venue | str, when: datetime | None = None) -> datetime:
    """When this venue next trades, in UTC. Now, if it is already open."""
    venue = Venue(venue)
    if venue is Venue.CRYPTO:
        return (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if is_open(venue, when):
        return (when or datetime.now(timezone.utc)).astimezone(timezone.utc)

    session = SESSIONS[venue]
    local = _local(venue, when)

    # Normalise to today's opening bell, then step forward a day at a time.
    # An earlier version branched on whether the candidate was past the open,
    # which pinned a pre-open Saturday to the same day for all thirty
    # iterations and then raised "the holiday table is probably wrong" — a
    # message pointing at the wrong thing entirely.
    candidate = local.replace(hour=session.opens.hour, minute=session.opens.minute,
                              second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)

    for _ in range(30):          # far enough past any holiday run
        if (candidate.weekday() in session.weekdays
                and candidate.date() not in HOLIDAYS.get(venue, set())):
            return candidate.astimezone(timezone.utc)
        candidate += timedelta(days=1)
    raise RuntimeError(f"{venue.value} has no open session in the next 30 days — "
                       "the holiday table is probably wrong")


def status(when: datetime | None = None) -> str:
    """One line per venue, for the digest and the doctor."""
    lines = []
    for venue in Venue:
        local = _local(venue, when)
        if is_open(venue, when):
            lines.append(f"{venue.value}: open ({local:%H:%M} local)")
        else:
            nxt = next_open(venue, when)
            hours = (nxt - (when or datetime.now(timezone.utc))).total_seconds() / 3600
            lines.append(f"{venue.value}: closed ({local:%H:%M} local), "
                         f"opens in {hours:.1f}h")
    if holidays_stale(when):
        lines.append("Holiday table has run out — every unknown date is being "
                     f"treated as a trading day. Update HOLIDAYS past "
                     f"{HOLIDAYS_KNOWN_THROUGH.isoformat()}.")
    return "\n".join(lines)


def should_poll(symbol: str, when: datetime | None = None) -> tuple[bool, str]:
    """Whether to fetch this symbol now, and why not if not.

    Returns the reason so a caller can tell a closed market apart from a failed
    fetch. Conflating those is how a timezone bug becomes a market observation.
    """
    venue = venue_for(symbol)
    if is_open(venue, when):
        return True, "market open"
    local = _local(venue, when)
    if venue is not Venue.CRYPTO and local.date() in HOLIDAYS.get(venue, set()):
        return False, f"{venue.value} holiday"
    if local.weekday() not in SESSIONS[venue].weekdays:
        return False, "weekend"
    return False, f"{venue.value} closed ({local:%H:%M} local)"
