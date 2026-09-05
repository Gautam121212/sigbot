"""End-to-end proof that the board is a loop, not a static list.

Everything else tests a piece. This tests the claim: the models run on the board,
outcomes come back, bad records get dropped one or two at a time, and the
replacement comes from the screen. If any link is missing the loop is decorative,
and the whole design rests on it turning.
"""
from __future__ import annotations

import pytest

from sigbot.config import POOL
from sigbot.runner import board_assets, board_records
from sigbot.shadow import ShadowLedger
from sigbot.watchlist import RULES, Flag, Watchlist


@pytest.fixture
def settings(tmp_path):
    from sigbot.config import Settings

    return Settings(shadow_db=str(tmp_path / "s.db"),
                    watchlist_db=str(tmp_path / "w.db"))


from tests.conftest import write_records as _record


# ------------------------------------------------- the models follow the board

def test_models_run_on_the_board_not_a_fixed_list(settings):
    """A board that rotates while the models predict a fixed universe is not a loop."""
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    on_board = set(wl.symbols())

    assets = board_assets(settings)
    assert assets, "collectors got an empty list"
    assert {a.symbol for a in assets} <= on_board
    assert len(assets) == len(on_board)


def test_cold_start_falls_back_to_the_universe(settings):
    """With no board yet, the models must still have something to run on."""
    assert board_assets(settings), "cold start left the collectors with nothing"


def test_board_changes_change_what_the_models_see(settings):
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    before = {a.symbol for a in board_assets(settings)}
    victim = sorted(before)[0]
    wl.drop(victim, 150, 0.38, 0.47, "test")
    after = {a.symbol for a in board_assets(settings)}
    assert victim in before and victim not in after


# ---------------------------------------------------- outcomes come back round

def test_outcomes_reach_the_board(settings):
    led = ShadowLedger(settings.shadow_db)
    _record(led, "news", "NVDA", 150, 0.65)
    _record(led, "daily", "NVDA", 100, 0.60)

    rec = board_records(settings)
    assert "NVDA" in rec
    n, hits = rec["NVDA"]
    assert n == 250, "checks from different models must pool"
    assert 0 < hits < n


def test_a_bad_record_turns_the_asset_red(settings):
    led = ShadowLedger(settings.shadow_db)
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    victim = sorted(wl.symbols())[0]
    _record(led, "news", victim, 150, 0.38)

    slot = next(s for s in wl.review(board_records(settings)) if s.symbol == victim)
    assert slot.flag is Flag.RED
    assert "loses to a coin flip" in slot.reason


# ------------------------------------------------------------- rotation turns

def test_rotation_drops_one_or_two_and_backfills(settings):
    led = ShadowLedger(settings.shadow_db)
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    before = set(wl.symbols())
    for sym in sorted(before)[:6]:
        _record(led, "news", sym, 150, 0.36)

    out = wl.rotate(board_records(settings), POOL)
    assert 0 < len(out["dropped"]) <= RULES.max_drops_per_cycle
    assert out["size"] == 100, "the board must stay full"
    after = set(wl.symbols())
    assert after != before
    assert len(after - before) == len(out["dropped"]), "a replacement per drop"


def test_rotation_is_gradual_across_cycles(settings):
    """Six failing assets take several cycles to clear — never one purge."""
    led = ShadowLedger(settings.shadow_db)
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    failing = sorted(wl.symbols())[:6]
    for sym in failing:
        _record(led, "news", sym, 150, 0.36)

    cycles, removed = 0, 0
    while removed < len(failing) and cycles < 8:
        out = wl.rotate(board_records(settings), POOL)
        removed += len(out["dropped"])
        cycles += 1
        if not out["dropped"]:
            break
    assert cycles >= 3, f"six failures cleared in {cycles} cycles — too fast"
    assert removed == len(failing)


def test_a_healthy_board_does_not_churn(settings):
    led = ShadowLedger(settings.shadow_db)
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    for sym in sorted(wl.symbols())[:10]:
        _record(led, "news", sym, 150, 0.62)

    out = wl.rotate(board_records(settings), POOL)
    assert out["dropped"] == [], "a good board must not rotate for the sake of it"


def test_a_thin_bad_record_is_not_enough_to_drop(settings):
    """Fewer than the minimum checks must not trigger a drop, however bad."""
    led = ShadowLedger(settings.shadow_db)
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    for sym in sorted(wl.symbols())[:5]:
        _record(led, "news", sym, RULES.drop_min_n - 20, 0.20)

    assert wl.rotate(board_records(settings), POOL)["dropped"] == []


def test_replacements_come_from_the_screen_ordering(settings):
    """Rotation takes the head of the candidate list it is given."""
    led = ShadowLedger(settings.shadow_db)
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    for sym in sorted(wl.symbols())[:3]:
        _record(led, "news", sym, 150, 0.36)

    held = set(wl.symbols())
    ranked = [a for a in POOL if a.symbol not in held]
    assert ranked, "pool must be larger than the board"
    out = wl.rotate(board_records(settings), ranked)
    added = set(wl.symbols()) - held
    top = {a.symbol for a in ranked[: len(added) * 4]}
    assert added <= top, "replacements ignored the ordering they were handed"
    assert out["dropped"]


def test_a_dropped_asset_stops_being_predicted(settings):
    """The full circuit: bad record -> dropped -> models no longer see it."""
    led = ShadowLedger(settings.shadow_db)
    wl = Watchlist(settings.watchlist_db)
    wl.seed(POOL)
    victim = sorted(wl.symbols())[0]
    _record(led, "news", victim, 150, 0.36)

    assert victim in {a.symbol for a in board_assets(settings)}
    wl.rotate(board_records(settings), POOL)
    assert victim not in {a.symbol for a in board_assets(settings)}
    assert victim in {g["symbol"] for g in wl.graveyard()}


def test_every_forecast_is_recorded_not_only_the_signals(tmp_path):
    """Skipping HOLDs threw away 98 of 100 measurable predictions a day.

    At that rate an asset needed decades to reach the checks a tier requires —
    the learning loop was real and fed almost nothing.
    """
    import contextlib
    import io
    import sqlite3

    from sigbot.config import Settings
    from sigbot.messenger import ConsoleMessenger
    from sigbot.providers.market import SyntheticProvider
    from sigbot.runner import run_daily

    st = Settings(shadow_db=str(tmp_path / "s.db"),
                  watchlist_db=str(tmp_path / "w.db"))
    with contextlib.redirect_stdout(io.StringIO()):
        run_daily(messenger=ConsoleMessenger(), market=SyntheticProvider(), settings=st)

    with sqlite3.connect(tmp_path / "s.db") as con:
        total, alerted = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(alerted),0) FROM predictions").fetchone()
    assert total > 20, f"only {total} forecasts recorded — HOLDs are being dropped"
    assert alerted <= total, "alerted cannot exceed recorded"


def test_a_hold_is_recorded_but_not_alerted(tmp_path):
    from sigbot.shadow import ShadowLedger

    led = ShadowLedger(tmp_path / "s.db")
    led.record("daily", "NVDA", "BUY", 0.5, 0.01, 100.0, 24, alerted=False)
    led.record("daily", "AAPL", "BUY", 0.7, 0.02, 100.0, 24, alerted=True)
    import sqlite3

    with sqlite3.connect(tmp_path / "s.db") as con:
        rows = dict(con.execute("SELECT symbol, alerted FROM predictions"))
    assert rows == {"NVDA": 0, "AAPL": 1}


def test_an_older_ledger_gains_the_alerted_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "model TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, score REAL, "
            "expected_move REAL, created_at TEXT NOT NULL, resolve_after TEXT NOT NULL, "
            "entry_price REAL, exit_price REAL, realised_ret REAL, hit INTEGER, payload TEXT)")

    from sigbot.shadow import ShadowLedger

    led = ShadowLedger(path)
    pid = led.record("daily", "X", "BUY", 0.6, 0.01, 100.0, 24, alerted=False)
    assert pid > 0
