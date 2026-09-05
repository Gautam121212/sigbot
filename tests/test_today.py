"""Tests for today's calls.

The design question was whether a 72% score may wear a green badge. It may —
labelled as a claim, beside its check count. What it may not do is wear the
colour the Board reserves for a measured record.
"""
from __future__ import annotations

import random

from sigbot.shadow import ShadowLedger
from sigbot.today import GREEN, GREY, RED, STRONG, read, render


def _ledger(path):
    return ShadowLedger(str(path))


def test_a_strong_claim_is_green_but_says_claims(tmp_path):
    led = _ledger(tmp_path / "s.db")
    led.record("daily", "NVDA", "BUY", 0.72, 0.015, 100.0)
    call = read(str(tmp_path / "s.db")).calls[0]

    assert call.colour == GREEN
    assert "claims" in call.claim
    assert "is" not in call.claim.split("claims")[0]


def test_a_claim_with_no_record_says_so_in_words(tmp_path):
    """A screen of green claims reads as a screen of opportunities. The check
    count is what stops that."""
    led = _ledger(tmp_path / "s.db")
    led.record("daily", "NVDA", "BUY", 0.72, 0.015, 100.0)
    call = read(str(tmp_path / "s.db")).calls[0]

    assert call.checks == 0
    assert "untested" in call.record


def test_a_claim_with_a_record_shows_both(tmp_path):
    led = _ledger(tmp_path / "s.db")
    rng = random.Random(5)
    for _ in range(40):
        pid = led.record("daily", "AVGO", "BUY", 0.58, 0.01, 100.0,
                         horizon_hours=-1)
        led.resolve(pid, 102.0 if rng.random() < 0.55 else 98.0,
                    bar_open=100.0, bar_high=102.5, bar_low=97.5)
    led.record("daily", "AVGO", "BUY", 0.72, 0.015, 100.0)

    call = next(c for c in read(str(tmp_path / "s.db")).calls
                if c.symbol == "AVGO")
    assert call.colour == GREEN
    assert call.checks == 40
    assert "worst case" in call.record


def test_resolved_history_does_not_reappear_as_todays_calls(tmp_path):
    """Including scored rows made one asset's history show up as a dozen
    duplicate calls — manufacturing the appearance of many opportunities
    from one."""
    led = _ledger(tmp_path / "s.db")
    for _ in range(30):
        pid = led.record("daily", "AVGO", "BUY", 0.58, 0.01, 100.0,
                         horizon_hours=-1)
        led.resolve(pid, 102.0, bar_open=100.0, bar_high=102.5, bar_low=97.5)
    led.record("daily", "NVDA", "BUY", 0.68, 0.015, 100.0)

    calls = read(str(tmp_path / "s.db")).calls
    assert [c.symbol for c in calls] == ["NVDA"]


def test_a_weak_claim_is_red_not_hidden(tmp_path):
    led = _ledger(tmp_path / "s.db")
    led.record("daily", "TCS.NS", "SELL", 0.38, 0.015, 100.0)
    assert read(str(tmp_path / "s.db")).calls[0].colour == RED


def test_holds_are_grey_and_counted(tmp_path):
    """100 holds is the answer, not the absence of one."""
    led = _ledger(tmp_path / "s.db")
    for i in range(100):
        led.record("daily", f"A{i}", "HOLD", 0.5, 0.0, 100.0)

    today = read(str(tmp_path / "s.db"))
    assert today.open_now == 100
    assert all(c.colour == GREY for c in today.calls)

    text = render(today)
    assert "Every asset came back HOLD" in text
    assert "a hold that would have risen is a data point too" in text


def test_the_footer_refuses_to_let_a_claim_pass_as_evidence(tmp_path):
    led = _ledger(tmp_path / "s.db")
    led.record("daily", "NVDA", "BUY", 0.72, 0.015, 100.0)
    text = render(read(str(tmp_path / "s.db")))

    assert "the model's claim, not its record" in text
    assert "Nothing here has been checked yet" in text
    assert "sigbot.progress" in text


def test_no_forecasts_at_all_is_called_a_fault(tmp_path):
    """A job that never ran is a broken job, not a quiet market."""
    _ledger(tmp_path / "s.db")
    text = render(read(str(tmp_path / "s.db")))
    assert "No forecasts recorded in the last day at all" in text
    assert "both are faults" in text


def test_everything_resolved_is_not_a_fault(tmp_path):
    """Nothing open is not the same as nothing made. Reporting a fault when
    every forecast has been scored describes a healthy day as a broken one."""
    led = _ledger(tmp_path / "s.db")
    for i in range(5):
        pid = led.record("daily", f"A{i}", "BUY", 0.55, 0.01, 100.0,
                         horizon_hours=-1)
        led.resolve(pid, 102.0, bar_open=100.0, bar_high=102.5, bar_low=99.0)

    text = render(read(str(tmp_path / "s.db")))
    assert "Nothing open" in text
    assert "have been scored" in text
    assert "not a fault" in text
    assert "faults" not in text.replace("not a fault", "")


def test_the_signal_bar_quoted_is_the_models_own():
    from sigbot.today import _band

    _colour, claim = _band(0.72, "BUY")
    assert f"{STRONG:.0%}" in claim
