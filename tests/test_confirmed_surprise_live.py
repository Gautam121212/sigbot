"""The confirmed-surprise indicator, live on paper."""
from __future__ import annotations

import json

import sigbot.runner as runner
from sigbot.alignment import _stocks_trades, review_setups
from sigbot.shadow import ShadowLedger


def test_only_big_beats_the_market_confirmed_are_recorded(tmp_path):
    led = ShadowLedger(str(tmp_path / "s.db"))
    surprises = {"BEAT": 18.0, "SMALL": 4.0, "MISS": -20.0}
    cands = [("BEAT", 100.0, 0.05), ("SMALL", 50.0, 0.04), ("MISS", 30.0, 0.03),
             ("NONE", 20.0, 0.06)]
    n = runner.record_confirmed_surprises(led, cands, lookup=surprises.get)
    assert n == 1
    import sqlite3
    con = sqlite3.connect(led.path)
    sym, payload, horizon = con.execute(
        "SELECT symbol, payload, strftime('%s', resolve_after) - strftime('%s', created_at) "
        "FROM predictions").fetchone()
    info = json.loads(payload)
    assert sym == "BEAT" and info["setup"] == "confirmed-surprise"
    assert info["taken"] is False, "paper only until its live record earns more"
    assert abs(horizon / 3600 - 19 * 24 * 7 // 5) <= 1, "the 19-day horizon history measured"


def test_look_ups_are_capped_per_run(tmp_path):
    led = ShadowLedger(str(tmp_path / "s.db"))
    calls = []

    def lookup(sym):
        calls.append(sym)
        return None

    cands = [(f"S{i}", 10.0, 0.03) for i in range(100)]
    runner.record_confirmed_surprises(led, cands, lookup=lookup)
    assert len(calls) == runner.SURPRISE_LOOKUPS_PER_RUN


def test_a_failed_look_up_is_no_signal():
    def broken(sym):
        raise OSError("down")
    assert runner._earnings_surprise("X", broken) is None


def test_the_review_tracks_the_paper_setup(tmp_path):
    led = ShadowLedger(str(tmp_path / "s.db"))
    runner.record_confirmed_surprises(led, [("BEAT", 100.0, 0.05)], lookup=lambda s: 18.0)
    import sqlite3
    con = sqlite3.connect(led.path)
    pid = con.execute("SELECT id FROM predictions").fetchone()[0]
    led.resolve(pid, 103.0)
    names = {r.setup: r for r in review_setups(_stocks_trades(led.path))}
    assert "confirmed-surprise" in names and names["confirmed-surprise"].trades == 1


def test_the_review_quotes_the_core_satellite_account():
    from sigbot.alignment import check_growth
    from sigbot.benchmarks import ACCOUNT_NET_MONTH
    assert f"{ACCOUNT_NET_MONTH * 100:+.2f}%" in check_growth([]).expectation
