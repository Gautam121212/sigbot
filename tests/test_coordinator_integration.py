"""Coordinator integration — OperatingLoop is the single prediction path."""
from sigbot.coordinator import JOBS, _LOOP_ENABLED


def test_old_prediction_jobs_absent():
    """The five old prediction runners must not be in the schedule."""
    names = {name for name, *_ in JOBS}
    for old in ("stocks", "news", "crypto", "ventures", "ideas"):
        assert old not in names, f"old job '{old}' still in schedule"


def test_operating_loop_is_registered():
    names = {name for name, *_ in JOBS}
    assert "operating_loop" in names


def test_loop_enabled():
    assert _LOOP_ENABLED is True


def test_no_duplicate_job_names():
    names = [name for name, *_ in JOBS]
    assert len(names) == len(set(names))


def test_infrastructure_jobs_still_present():
    """resolve, paper, publish, day_summary must remain — they are not
    prediction jobs and are still needed."""
    names = {name for name, *_ in JOBS}
    for infra in ("resolve", "paper", "publish", "day_summary"):
        assert infra in names
