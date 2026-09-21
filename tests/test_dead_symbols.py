"""Delisted names are remembered and skipped — and retried later."""
from __future__ import annotations

import inspect
import json
from datetime import date, timedelta

import sigbot.runner as runner


def test_a_name_that_returned_nothing_is_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner._mark_dead("GONE.NS")
    assert runner._is_dead("GONE.NS", runner._dead_symbols())


def test_it_is_retried_after_thirty_days(tmp_path, monkeypatch):
    """A suspended stock can resume trading."""
    monkeypatch.chdir(tmp_path)
    old = (date.today() - timedelta(days=runner.DEAD_RETRY_DAYS + 1)).isoformat()
    (tmp_path / runner.DEAD_FILE).write_text(json.dumps({"OLD.NS": old}))
    assert not runner._is_dead("OLD.NS", runner._dead_symbols())


def test_only_an_empty_history_marks_a_name_dead():
    """A SHORT history is a new listing, not a dead one — and new listings
    are exactly what a wide scan exists to find."""
    src = inspect.getsource(runner.run_stocks)
    assert "if len(bars) == 0:\n                _mark_dead(asset.symbol)" in src


def test_dead_names_are_left_out_of_the_pool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    everyone = {a.symbol for a in runner.board_assets()}
    victim = sorted(everyone)[0]
    runner._mark_dead(victim)
    assert victim not in {a.symbol for a in runner.board_assets()}


def test_the_memory_reaches_the_machines_that_run_the_scan():
    """The daily scan runs on GitHub, which starts from a fresh checkout. A
    gitignored memory would work on a laptop and do nothing where it matters."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "dead_symbols.json" not in (root / ".gitignore").read_text()
    assert "dead_symbols.json" in (root / "scripts" / "ship.sh").read_text()
