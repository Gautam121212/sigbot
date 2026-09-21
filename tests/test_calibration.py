"""Live results against history: the learning-gap check."""
from __future__ import annotations

from sigbot.calibration import CONSISTENT, DIVERGENT, EARLY, check
from sigbot.shadow import ShadowLedger


def _fill(ledger, model, n, wins):
    for i in range(n):
        pid = ledger.record(model, f"S{i}", "BUY", 0.6, 0.02, 100.0)
        ledger.resolve(pid, 101.0 if i < wins else 99.0)


def test_a_model_matching_history_is_consistent(tmp_path):
    led = ShadowLedger(str(tmp_path / "s.db"))
    _fill(led, "daily", 200, 100)
    g = {x.model: x for x in check(str(tmp_path / "s.db"))}["daily"]
    assert g.verdict == CONSISTENT


def test_too_few_checks_is_never_a_verdict(tmp_path):
    led = ShadowLedger(str(tmp_path / "s.db"))
    _fill(led, "stocks", 10, 9)
    g = {x.model: x for x in check(str(tmp_path / "s.db"))}["stocks"]
    assert g.verdict == EARLY


def test_a_model_beating_history_is_flagged_as_divergent(tmp_path):
    """Built on fixed data. The first version read the real ledger, which
    differs between machines — it passed on one and failed on another."""
    led = ShadowLedger(str(tmp_path / "s.db"))
    for i in range(200):
        side = "BUY" if i % 2 else "SELL"
        pid = led.record("news", f"S{i}", side, 0.6, 0.02, 100.0)
        up = i % 2 == 1 if i < 170 else i % 2 == 0
        led.resolve(pid, 101.0 if up else 99.0)
    g = {x.model: x for x in check(str(tmp_path / "s.db"))}["news"]
    assert g.verdict == DIVERGENT and g.live_edge > 0
