"""The fixes that make the live record measure the strategy that was tested."""
from __future__ import annotations

import inspect
import json

import sigbot.runner as runner
from sigbot.scan import CANDIDATES, scan_row
from sigbot.shadow import ShadowLedger

BREAKOUT = {"close": 110.0, "hi52": 108.0, "sma_50": 100.0, "sma_200": 90.0,
            "volume": 3_000_000, "volume_ma_20": 1_000_000}


def test_momentum_only_buys_in_a_calm_uptrend():
    assert scan_row("NVDA", {**BREAKOUT, "index_regime": "up/calm"}) is not None
    for regime in ("down/volatile", "up/volatile", "down/calm"):
        assert scan_row("NVDA", {**BREAKOUT, "index_regime": regime}) is None, regime
    assert scan_row("NVDA", BREAKOUT) is None, "unknown regime fails closed"


def test_each_school_holds_for_its_own_period():
    holds = {c.name: c.hold_days for c in CANDIDATES}
    assert holds["momentum-breakout"] == 20
    # Capitulation holds 20 days: a pre-registered test of 5 / 10 / 20 found
    # panic rebounds take weeks (+1.04% / +0.62% / +1.09% at 20 days).
    assert holds["capitulation"] == 20
    assert all(d == 10 for n, d in holds.items()
               if n not in ("momentum-breakout", "capitulation"))


def test_trades_are_scored_at_their_real_holding_period():
    """They were scored after 24 hours while every test measured 10 days."""
    src = inspect.getsource(runner.run_stocks)
    assert "hit.candidate.hold_days * 24 * 7 // 5" in src
    assert "close, 24,\n                      payload=liquidity" not in src


def test_sectors_are_real_cached_and_capped(tmp_path, monkeypatch):
    """Every name was "unknown", so "two per sector" meant two a day."""
    monkeypatch.chdir(tmp_path)
    runner._sector_lookups["n"] = 0
    calls = []

    def lookup(sym):
        calls.append(sym)
        return "Technology"

    assert runner._sector_of("AMD", lookup) == "Technology"
    assert runner._sector_of("AMD", lookup) == "Technology"
    assert calls == ["AMD"], "looked up once, then remembered"

    def broken(sym):
        raise OSError("down")

    assert runner._sector_of("XYZ", broken) == "unknown", "fails to the cautious bucket"
    runner._sector_lookups["n"] = runner.SECTOR_LOOKUPS_PER_RUN
    assert runner._sector_of("NEW", lookup) == "unknown", "capped per run"
    runner._sector_lookups["n"] = 0


def test_open_positions_carry_over_between_runs(tmp_path):
    """Each run started from an empty book, so the position limits applied
    only within one day. With ten- and sixty-day holds that let dozens build."""
    ledger = ShadowLedger(str(tmp_path / "s.db"))
    for sym, taken, sector in (("A", True, "Technology"), ("B", True, "Technology"),
                               ("C", False, "Energy"), ("D", True, "Energy")):
        ledger.record("stocks", sym, "BUY", 0.7, 0.05, 100.0, 336,
                      payload=json.dumps({"taken": taken, "sector": sector}))
    n, sectors = runner._open_book(ledger)
    assert n == 3 and sectors == {"Technology": 2, "Energy": 1}


def test_the_seeded_state_counts_the_open_book(tmp_path):
    class S:
        shadow_db = str(tmp_path / "s.db")
    ledger = ShadowLedger(S.shadow_db)
    for sym in ("A", "B"):
        ledger.record("stocks", sym, "BUY", 0.7, 0.05, 100.0, 336,
                      payload=json.dumps({"taken": True, "sector": "Energy"}))
    state = runner._seed_risk_state(ledger, S)
    assert state.open_positions == 2 and state.open_risk > 0


def test_follow_on_buys_the_rebound_after_a_leader_falls():
    sec = {"AMD": "Technology", "TXN": "Technology", "MU": "Technology",
           "KO": "Consumer Defensive"}.get
    picks = runner.sympathy_rebounds(
        {"NVDA": -0.06, "AMD": -0.02, "TXN": -0.045, "MU": -0.035, "KO": -0.05}, sec)
    assert picks == [("TXN", "NVDA"), ("MU", "NVDA")]
    assert runner.sympathy_rebounds({"NVDA": -0.02, "TXN": -0.05}, sec) == [], \
        "no leader fell far enough"


def test_the_losing_follow_bet_is_off():
    """Following the leader lost on 745,570 cases; it must not quietly return."""
    assert runner.LEGACY_FOLLOW is False


def test_the_new_memory_files_reach_the_github_runs():
    from pathlib import Path
    ship = (Path(__file__).resolve().parents[1] / "scripts" / "ship.sh").read_text()
    for f in ("sectors.json", "learning_log.jsonl", "dead_symbols.json"):
        assert f in ship, f
