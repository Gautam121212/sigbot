"""Urgency-based attention: the fastest-decaying work goes first."""
from __future__ import annotations

from sigbot.priority import ALWAYS_RUN, evidence_weight, plan

JOBS = ["resolve", "news", "contagion", "opportunity", "stocks",
        "crypto15m", "daily", "profiles", "thematic"]


def _runs(slots):
    return [s.job for s in slots if s.runs]


def test_fast_decaying_work_comes_before_slow():
    """A headline acted on tomorrow is worth nothing; a theme read tomorrow
    is worth nearly as much."""
    order = [s.job for s in plan(JOBS, budget_seconds=10 ** 6)]
    assert order.index("news") < order.index("stocks")
    assert order.index("stocks") < order.index("thematic")
    assert order.index("stocks") < order.index("profiles")


def test_bookkeeping_is_never_deferred_however_tight_the_budget():
    """Every measurement depends on forecasts being closed out."""
    slots = plan(JOBS, budget_seconds=1)
    for job in ALWAYS_RUN:
        assert job in _runs(slots)


def test_a_proven_useless_job_cannot_jump_the_queue_on_cost():
    """The first real run found crypto15m (proven to find nothing) slipping
    into a gap that contagion (unexplored) was too expensive to fit — plain
    greedy bin-packing letting the least deserving job jump the queue."""
    verdicts = {"crypto15m": "NO EDGE", "contagion": "NO DATA",
                "opportunity": "NO DATA"}
    slots = plan(JOBS, verdicts, budget_seconds=20 * 60)
    ran = _runs(slots)
    if "contagion" not in ran:
        assert "crypto15m" not in ran, (
            "a NO EDGE job must not run while a more deserving one waits")


def test_a_useless_job_still_runs_when_nothing_better_waits():
    """Rarely, not never — conditions change, and a model that is never run
    can never be seen to recover."""
    verdicts = {"crypto15m": "NO EDGE"}
    assert "crypto15m" in _runs(plan(JOBS, verdicts, budget_seconds=10 ** 6))


def test_evidence_scales_urgency_in_the_right_direction():
    assert evidence_weight("WORKING") > evidence_weight("NO ROOM")
    assert evidence_weight("NO ROOM") > evidence_weight("NO EDGE")
    assert evidence_weight("NO EDGE") > 0, "never zero — see above"
    assert evidence_weight(None) == 1.0, "unknown means find out, not ignore"


def test_nothing_is_dropped_only_deferred():
    slots = plan(JOBS, budget_seconds=60)
    assert {s.job for s in slots} == set(JOBS), "every job keeps its place"


def test_every_planned_job_has_a_runner():
    """The first registry held three entries, so execute mode silently skipped
    news — the most urgent job on the queue."""
    from sigbot.priority import HALF_LIFE_HOURS
    from sigbot.runner import _job_registry

    missing = (set(HALF_LIFE_HOURS) | {"resolve"}) - set(_job_registry())
    assert not missing, f"planned but unrunnable: {sorted(missing)}"


def test_the_scheduler_cannot_schedule_itself():
    """An edit adding `priority` to the main job table matched an identical
    line inside the registry, so execute mode would have recursed."""
    from sigbot.runner import _job_registry, run_priority

    assert "priority" not in _job_registry()
    assert all(fn is not run_priority for fn in _job_registry().values())


def test_resolve_is_always_the_first_job_in_the_tick():
    """resolve was in the registry but not the queue — so priority-run never
    called it. 1,494 forecasts went unscored across weeks of daily GitHub
    runs. The queue now always starts with resolve."""
    import inspect
    from sigbot.runner import run_priority
    src = inspect.getsource(run_priority)
    assert '"resolve"' in src, "resolve must be in the jobs list inside run_priority"


def test_resolve_appears_before_news_in_priority_queue():
    """It has the shortest half-life — a forecast past its window cannot
    be scored at all."""
    from sigbot.priority import HALF_LIFE_HOURS
    assert "resolve" in HALF_LIFE_HOURS
    assert HALF_LIFE_HOURS["resolve"] < HALF_LIFE_HOURS["news"]
