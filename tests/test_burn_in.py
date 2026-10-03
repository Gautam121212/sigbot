"""Burn-in runner — live SYSTEM STATUS from real verification, paper-only."""
from datetime import datetime, timedelta, timezone

from sigbot.burn_in import BURN_IN_CHAMPION, BurnIn
from sigbot.operating_loop import ModelState
from sigbot.production_integration import CycleObservation

NOW = datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc)


def _obs(fam, **kw):
    base = dict(data_as_of=NOW - timedelta(hours=1), data_received_at=NOW,
                prediction_made_at=NOW, prediction_id="p", stored=True,
                in_api=True, website_value=1.0, db_value=1.0, now=NOW)
    base.update(kw)
    return CycleObservation(family=fam, **base)


def _healthy_tick():
    return {"stocks": _obs("stocks", data_as_of=NOW - timedelta(days=1)),
            "news": _obs("news"),
            "crypto": _obs("crypto", data_as_of=NOW - timedelta(minutes=30))}


# ── all five families registered on champion ────────────────────────────────
def test_all_families_registered():
    b = BurnIn()
    lcs = b.integration.command_center.lifecycles
    for fam in ("stocks", "ventures", "news", "crypto", "ideas"):
        assert fam in lcs
        assert lcs[fam].champion == BURN_IN_CHAMPION


# ── phase 1 keeps capital blocked no matter what ────────────────────────────
def test_phase1_capital_always_blocked():
    b = BurnIn(phase_1_paper_only=True)
    report = b.run_tick(_healthy_tick())
    assert "Capital     BLOCKED" in report


def test_healthy_tick_all_active():
    b = BurnIn()
    report = b.run_tick(_healthy_tick())
    assert report.count("ACTIVE") == 5           # all five families
    assert b.process_healthy()


# ── pit surfaced as caveat, not clean pass ──────────────────────────────────
def test_pit_shown_as_caveat():
    b = BurnIn()
    report = b.run_tick(_healthy_tick(), pit_caveat=True)
    assert "CAVEAT" in report


# ── research shown as running ───────────────────────────────────────────────
def test_research_shown_running():
    b = BurnIn()
    report = b.run_tick(_healthy_tick())
    assert "research      RUNNING" in report or "research     RUNNING" in report


# ── a dead data source quarantines and shows in status ──────────────────────
def test_dead_data_source_quarantines_and_reports():
    b = BurnIn()
    b.run_tick(_healthy_tick())
    dead = {"crypto": _obs("crypto", data_as_of=None, data_received_at=None,
                           prediction_made_at=None, prediction_id=None,
                           stored=False, in_api=False, website_value=None,
                           db_value=None)}
    report = b.run_tick(dead)
    assert "crypto     QUARANTINED" in report
    assert "data         FAIL" in report
    assert not b.process_healthy()
    assert "crypto" in b.quarantined_families()


# ── process verdict is about process, not money ─────────────────────────────
def test_process_healthy_independent_of_returns():
    """A healthy process is about pipeline soundness — there is no P&L input."""
    b = BurnIn()
    b.run_tick(_healthy_tick())
    # process_healthy takes no return/pnl argument at all
    import inspect
    sig = inspect.signature(b.process_healthy)
    assert len(sig.parameters) == 0
    assert b.process_healthy()


# ── stale website shows in the report and traces to website ─────────────────
def test_stale_website_reported():
    b = BurnIn()
    tick = {"stocks": _obs("stocks", data_as_of=NOW - timedelta(days=1),
                           website_value=9.9, db_value=2.1)}   # mismatch
    report = b.run_tick(tick)
    assert "website      FAIL" in report


# ── ventures (quarterly) not firing a tick is fine ──────────────────────────
def test_families_without_observation_keep_prior_state():
    b = BurnIn()
    # only stocks fires; ventures/ideas have no obs — they stay ACTIVE
    b.run_tick({"stocks": _obs("stocks", data_as_of=NOW - timedelta(days=1))})
    assert b.integration.command_center.lifecycles["ventures"].state == ModelState.ACTIVE


# ── burn-in does not trade or mutate ────────────────────────────────────────
def test_burn_in_does_not_trade_or_change_models():
    b = BurnIn()
    assert not hasattr(b, "place_order")
    assert not hasattr(b, "promote_model")
    assert not hasattr(b, "retune")
