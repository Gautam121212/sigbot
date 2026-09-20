"""Tests for the daily digest.

It exists because the daily job only spoke when a forecast cleared the gates,
which on a normal day is never. You cannot watch a system learn if it only
speaks when it is certain.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.daily_digest as dd  # noqa: E402

from sigbot.config import POOL  # noqa: E402
from sigbot.shadow import ShadowLedger  # noqa: E402
from sigbot.watchlist import Watchlist  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "ROOT", tmp_path)
    return tmp_path


def test_it_sends_something_even_with_nothing_to_report(home):
    text = dd.build()
    assert "Sigbot" in text
    assert "may not have run" in text
    assert len(text) > 100, "a digest that says nothing is the bug being fixed"


def test_resolved_window_uses_resolve_after_not_created_at(home):
    """Filtering on created_at reported 'nothing came due' every single day,
    because today's batch is always unresolved."""
    led = ShadowLedger(home / "shadow.db")
    for i in range(6):
        pid = led.record("daily", f"S{i}", "BUY", 0.6, 0.01, 100.0, horizon_hours=-1)
        led.resolve(pid, 103.0 if i % 2 else 97.0, bar_open=100.0,
                    bar_high=103.5 if i % 2 else 100.2, bar_low=97.0)
    led.record("daily", "TODAY", "BUY", 0.6, 0.01, 100.0)      # not due yet

    text = dd.build()
    assert "6 came due" in text
    assert "Worst case" in text


def test_misses_are_named_in_plain_words(home):
    led = ShadowLedger(home / "shadow.db")
    pid = led.record("daily", "NVDA", "BUY", 0.6, 0.02, 100.0, horizon_hours=-1)
    led.resolve(pid, 97.0, bar_open=100.0, bar_high=100.2, bar_low=97.0)
    text = dd.build()
    assert "NVDA" in text and "went the other way" in text


def test_everything_is_shown_not_only_what_cleared_the_gates(home):
    """The whole point: a WATCH-grade lean is shown, labelled, not hidden."""
    led = ShadowLedger(home / "shadow.db")
    led.record("daily", "GATED", "BUY", 0.70, 0.02, 100.0, alerted=True)
    led.record("daily", "UNGATED", "BUY", 0.55, 0.01, 100.0, alerted=False)
    text = dd.build()
    assert "GATED" in text and "UNGATED" in text
    assert "not advice" in text
    assert "no record yet" in text, "thin evidence must be labelled, not omitted"


def test_evidence_count_appears_once_a_record_exists(home):
    led = ShadowLedger(home / "shadow.db")
    for _ in range(30):
        pid = led.record("daily", "AVGO", "BUY", 0.6, 0.01, 100.0, horizon_hours=-1)
        led.resolve(pid, 103.0, bar_open=100.0, bar_high=103.5, bar_low=99.0)
    led.record("daily", "AVGO", "BUY", 0.6, 0.01, 100.0)
    assert "checks behind it" in dd.build()


def test_an_empty_board_is_not_reported_as_zero_coverage(home):
    """The models fall back to the default list. '0 assets' made a working
    system look dead."""
    ShadowLedger(home / "shadow.db")
    text = dd.build()
    assert "0 assets" not in text
    assert "Not built yet" in text and "run_screen" in text


def test_a_real_board_is_counted(home):
    ShadowLedger(home / "shadow.db")
    Watchlist(home / "watchlist.db").seed(POOL)
    assert "100 assets" in dd.build()


def test_output_fits_a_telegram_message(home):
    led = ShadowLedger(home / "shadow.db")
    for i in range(400):
        pid = led.record("daily", f"SYMBOL{i}", "BUY", 0.6, 0.01, 100.0, horizon_hours=-1)
        led.resolve(pid, 97.0, bar_open=100.0, bar_high=100.2, bar_low=97.0)
    text = dd.build()
    assert len(text) <= dd.TELEGRAM_LIMIT + 20, f"{len(text)} chars would be rejected"


def test_env_is_loaded_for_launchd(home, monkeypatch):
    """launchd does not inherit your shell, so credentials come from .env."""
    (home / ".env").write_text('TELEGRAM_TOKEN="1:AAH"\nTELEGRAM_CHAT_ID="9"\n')
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    dd.load_env()
    import os

    assert os.environ["TELEGRAM_TOKEN"] == "1:AAH"
    assert os.environ["TELEGRAM_CHAT_ID"] == "9"
