"""Does the model choose, or does it just describe?

A human trader looks at many and acts on few. The old two-number run log could
not tell the difference: the daily model spent forty runs reporting "55
considered, 0 signals" while writing 2,680 predictions — every one real,
scored, and invisible in the log meant to describe it.
"""
from __future__ import annotations

from sigbot.shadow import ShadowLedger


def test_the_run_log_separates_recorded_from_alerted(tmp_path):
    ledger = ShadowLedger(str(tmp_path / "s.db"))
    ledger.log_run("stocks", considered=250, signals=3, recorded=12)
    ledger.log_run("stocks", considered=250, signals=1, recorded=9)

    considered, recorded, alerted = ledger.selectivity("stocks")
    assert (considered, recorded, alerted) == (500, 21, 4), (
        "recording and alerting are different decisions and must be counted "
        "separately")


def test_an_old_style_run_still_reads_sensibly(tmp_path):
    """Jobs that do not distinguish the two fall back to signals, so the
    column addition cannot silently zero out existing history."""
    ledger = ShadowLedger(str(tmp_path / "s.db"))
    ledger.log_run("legacy", considered=100, signals=7)

    considered, recorded, alerted = ledger.selectivity("legacy")
    assert considered == 100
    assert recorded == alerted == 7


def test_selectivity_of_an_unrun_job_is_zero_not_an_error(tmp_path):
    ledger = ShadowLedger(str(tmp_path / "s.db"))
    assert ledger.selectivity("never-ran") == (0, 0, 0)


def test_a_model_that_records_everything_is_visible_as_such(tmp_path):
    """The failure this exists to catch: recording 100% of what was looked at
    is not selection, it is description."""
    ledger = ShadowLedger(str(tmp_path / "s.db"))
    ledger.log_run("describer", considered=55, signals=0, recorded=55)

    considered, recorded, _alerted = ledger.selectivity("describer")
    assert recorded == considered, "this is the shape of the problem"
