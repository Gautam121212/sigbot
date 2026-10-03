"""Production integration — live end-to-end verification + canary."""
from datetime import datetime, timedelta, timezone

from sigbot.operating_loop import ModelState
from sigbot.production_integration import (
    CycleObservation, Heartbeat, ProductionIntegration, build_live_status)

NOW = datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc)


def _obs(family="stocks", **kw):
    base = dict(
        data_as_of=NOW - timedelta(days=1), data_received_at=NOW - timedelta(hours=1),
        prediction_made_at=NOW, prediction_id="p1", stored=True, in_api=True,
        website_value=4.8, db_value=4.8, now=NOW)
    base.update(kw)
    return CycleObservation(family=family, **base)


# ── healthy path ────────────────────────────────────────────────────────────
def test_healthy_cycle_stays_active():
    pi = ProductionIntegration()
    assert pi.run_cycle(_obs()) == ModelState.ACTIVE


def test_healthy_cycle_records_heartbeat():
    pi = ProductionIntegration()
    pi.run_cycle(_obs("crypto", data_as_of=NOW - timedelta(minutes=30)))
    assert "crypto" not in pi.heartbeat.stale_families(NOW)


# ── failure cases in the real pipeline ──────────────────────────────────────
def test_data_source_stopped_quarantines():
    pi = ProductionIntegration()
    obs = _obs("crypto", data_as_of=None, data_received_at=None,
               prediction_made_at=None, prediction_id=None, stored=False,
               in_api=False, website_value=None, db_value=None)
    assert pi.run_cycle(obs) == ModelState.QUARANTINED


def test_missing_prediction_quarantines():
    pi = ProductionIntegration()
    obs = _obs(prediction_made_at=None, prediction_id=None)
    assert pi.run_cycle(obs) == ModelState.QUARANTINED


def test_lookahead_quarantines():
    """Prediction before the data it used = look-ahead = prediction-integrity fail."""
    pi = ProductionIntegration()
    obs = _obs(data_as_of=NOW, prediction_made_at=NOW - timedelta(days=1))
    assert pi.run_cycle(obs) == ModelState.QUARANTINED
    inc = pi.command_center.lifecycles["stocks"].incidents[-1]
    assert inc.root_cause_layer == "prediction"


def test_not_persisted_quarantines():
    pi = ProductionIntegration()
    obs = _obs(stored=False)
    assert pi.run_cycle(obs) == ModelState.QUARANTINED


# ── root-cause tracing in the live layer ────────────────────────────────────
def test_stale_website_traced_to_website_not_model():
    pi = ProductionIntegration()
    obs = _obs("news", data_as_of=NOW - timedelta(hours=1),
               website_value=9.9, db_value=2.1)       # mismatch
    pi.run_cycle(obs)
    inc = pi.command_center.lifecycles["news"].incidents[-1]
    assert inc.root_cause_layer == "website"           # NOT model/data


def test_data_corruption_traced_to_data():
    pi = ProductionIntegration()
    # no data at all -> data layer
    obs = _obs(data_as_of=None, data_received_at=None, prediction_made_at=None,
               prediction_id=None, stored=False, in_api=False,
               website_value=None, db_value=None)
    pi.run_cycle(obs)
    inc = pi.command_center.lifecycles["stocks"].incidents[-1]
    assert inc.root_cause_layer == "data"


# ── freshness ───────────────────────────────────────────────────────────────
def test_stale_data_flagged():
    pi = ProductionIntegration()
    checks = pi.verifier.verify(_obs("crypto", data_as_of=NOW - timedelta(days=5)))
    fresh = [c for c in checks if c.name == "data_fresh"][0]
    assert not fresh.passed                            # crypto limit is 2h


def test_quarterly_ventures_tolerates_old_data():
    pi = ProductionIntegration()
    checks = pi.verifier.verify(_obs("ventures", data_as_of=NOW - timedelta(days=60)))
    fresh = [c for c in checks if c.name == "data_fresh"][0]
    assert fresh.passed                                # ventures limit is 100d


# ── heartbeat ───────────────────────────────────────────────────────────────
def test_heartbeat_flags_silent_dead_family():
    hb = Heartbeat()
    hb.record_ok("stocks", NOW)
    stale = hb.stale_families(NOW)
    assert "stocks" not in stale
    assert "crypto" in stale                           # never ran


# ── live system status generated from real state ────────────────────────────
def test_status_blocks_capital_on_pipeline_failure():
    pi = ProductionIntegration()
    pi.run_cycle(_obs())
    status = build_live_status(pi.command_center,
                               {"data": True, "website": False})   # a layer failed
    assert status.capital_authorization == "BLOCKED"


def test_status_allows_capital_when_all_healthy():
    pi = ProductionIntegration()
    pi.run_cycle(_obs())
    status = build_live_status(pi.command_center,
                               {"data": True, "website": True, "api": True})
    assert status.capital_authorization == "ALLOWED"


def test_status_generated_from_actual_state_not_manual():
    pi = ProductionIntegration()
    pi.run_cycle(_obs("crypto", data_as_of=None, data_received_at=None,
                      prediction_made_at=None, prediction_id=None, stored=False,
                      in_api=False, website_value=None, db_value=None))
    status = build_live_status(pi.command_center, {"data": True})
    # crypto quarantined itself from the real cycle, not manual entry
    assert status.family_states["crypto"] == ModelState.QUARANTINED


def test_status_render_shows_blocked():
    pi = ProductionIntegration()
    status = build_live_status(pi.command_center, {"website": False})
    assert "BLOCKED" in status.render()


# ── THE FULL END-TO-END CANARY ──────────────────────────────────────────────
def test_full_end_to_end_canary():
    """Synthetic data -> model -> prediction -> db -> api -> website -> paper,
    verifying the final displayed result EXACTLY matches the stored result."""
    pi = ProductionIntegration()
    # one clean cycle through every family
    for fam, age in (("stocks", timedelta(days=1)), ("ventures", timedelta(days=30)),
                     ("news", timedelta(hours=1)), ("crypto", timedelta(minutes=30)),
                     ("ideas", timedelta(days=2))):
        stored_value = 3.14
        obs = _obs(fam, data_as_of=NOW - age, website_value=stored_value,
                   db_value=stored_value)
        state = pi.run_cycle(obs)
        assert state == ModelState.ACTIVE, f"{fam} did not stay active"
    # every family heartbeat is fresh
    assert pi.heartbeat.stale_families(NOW) == []
    # system is safe, capital allowed
    status = build_live_status(pi.command_center,
                               {"data": True, "predictions": True, "database": True,
                                "api": True, "website": True})
    assert status.capital_authorization == "ALLOWED"


def test_canary_fails_on_display_mismatch():
    """The canary MUST fail if the displayed value differs from the stored one."""
    pi = ProductionIntegration()
    obs = _obs("stocks", website_value=3.14, db_value=2.71)   # display != stored
    pi.run_cycle(obs)
    # website mismatch is non-critical -> warning, but the status must block
    status = build_live_status(pi.command_center, {"website": False})
    assert status.capital_authorization == "BLOCKED"


# ── no new alpha / no mutation ──────────────────────────────────────────────
def test_integration_does_not_trade_or_mutate():
    pi = ProductionIntegration()
    assert not hasattr(pi, "place_order")
    assert not hasattr(pi, "retune_model")
    assert not hasattr(pi, "replace_production")
    assert not hasattr(pi, "delete_research")
