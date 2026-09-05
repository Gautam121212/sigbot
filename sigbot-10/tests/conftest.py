"""Shared test fixtures.

## Why this file exists

Five test files each wrote ledger records with their own ad-hoc win-rate logic,
and several used `(i % 100) / 100 < rate`, which does not produce the rate it
claims once n is not a multiple of 100:

    asked for 58% over 140 records -> actually 70.0%
    asked for 49% over  60 records -> actually 81.7%
    asked for 52% over  20 records -> actually 100.0%

Those tests passed. Their assertions were loose enough to survive a fixture that
meant something different from what it said — which is the worse failure, because
a green suite then tells you nothing about the case you thought you were testing.

The fix is not a better formula. It is one helper instead of five, and a helper
that **checks its own output** before handing it back. A fixture that silently
produces the wrong thing is the one bug a test suite cannot catch for you.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sigbot.shadow import ShadowLedger


def write_records(ledger: ShadowLedger, model: str, symbol: str,
                  n: int, rate: float, side: str = "BUY") -> tuple[int, int]:
    """Write exactly `round(n * rate)` winning records. Returns (n, wins).

    Deterministic and exact: these tests assert on which side of a threshold a
    record falls, so an approximate rate is not merely imprecise, it changes
    what is being tested. The assertion at the end is the point of the helper —
    if the ledger disagrees with what was asked for, the test stops here rather
    than failing somewhere downstream with a confusing message.
    """
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"rate {rate} is not a proportion")
    wins = round(n * rate)
    for won in [True] * wins + [False] * (n - wins):
        pid = ledger.record(model, symbol, side, 0.6, 0.02, 100.0, horizon_hours=-1)
        # A win has to look like one to `classify_outcome`: it must clear costs
        # and, for a loss, not have run favourably first or it becomes a reversal.
        ledger.resolve(pid, 103.0 if won else 97.0, bar_open=100.0,
                       bar_high=103.5 if won else 100.2, bar_low=97.0)

    stats = ledger.stats(model).get(symbol)
    assert stats is not None, f"{symbol} did not reach the ledger"
    assert stats[0] == n, f"wrote {stats[0]} records, asked for {n}"
    assert round(stats[1] * n) == wins, (
        f"ledger holds {stats[1]:.1%} for {symbol}, asked for {rate:.1%}")
    return n, wins


@pytest.fixture
def records():
    """The helper, as a fixture, so tests do not each define their own."""
    return write_records


@pytest.fixture
def ledger(tmp_path):
    return ShadowLedger(tmp_path / "ledger.db")


# --- leak detection baseline -------------------------------------------------
# The stray-database check assumed the project folder starts empty. On a working
# install it does not: shadow.db, watchlist.db and patterns.db are the user's own
# record. Snapshot what was there before anything ran, so the check flags files
# the suite created and ignores files it merely found.

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DB_AT_START: set[str] = set()


def databases_at_start() -> set[str]:
    return set(_DB_AT_START)


@pytest.fixture(scope="session", autouse=True)
def _snapshot_databases():
    _DB_AT_START.clear()
    _DB_AT_START.update(p.name for p in PROJECT_ROOT.glob("*.db"))
    yield
