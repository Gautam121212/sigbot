"""System assurance — end-to-end checks + the production-lock containment."""
from datetime import datetime

import pytest

from sigbot.system_assurance import (
    ApprovedChampion, AssuranceReport, EndToEndAssurance, ExperimentLeakError,
    ModelOrigin, TradeAuthRequest, authorize_capital)

CHAMP = ApprovedChampion("SIGBOT-INFLECTION-001", "v2.0", "2026-01-01", "gen-001")


# ── the catastrophic case: experiment reaching the trading path ─────────────
def test_champion_can_authorize_capital():
    req = TradeAuthRequest("SIGBOT-INFLECTION-001", ModelOrigin.PRODUCTION, "gen-001")
    assert authorize_capital(req, CHAMP) is True


def test_research_model_cannot_trade():
    req = TradeAuthRequest("candidate-042", ModelOrigin.RESEARCH, "gen-002")
    with pytest.raises(ExperimentLeakError):
        authorize_capital(req, CHAMP)


def test_shadow_model_cannot_trade():
    req = TradeAuthRequest("challenger-A", ModelOrigin.SHADOW, "gen-002")
    with pytest.raises(ExperimentLeakError):
        authorize_capital(req, CHAMP)


def test_wrong_generation_production_model_cannot_trade():
    """Even a production-origin model that isn't the champion is blocked."""
    req = TradeAuthRequest("SIGBOT-INFLECTION-001", ModelOrigin.PRODUCTION, "gen-002")
    with pytest.raises(ExperimentLeakError):
        authorize_capital(req, CHAMP)


def test_wrong_model_id_cannot_trade():
    req = TradeAuthRequest("other-model", ModelOrigin.PRODUCTION, "gen-001")
    with pytest.raises(ExperimentLeakError):
        authorize_capital(req, CHAMP)


def test_leak_is_loud_not_silent():
    """A containment breach raises — it is never a quiet False return."""
    req = TradeAuthRequest("candidate-042", ModelOrigin.RESEARCH, "gen-002")
    try:
        authorize_capital(req, CHAMP)
        assert False, "should have raised"
    except ExperimentLeakError as e:
        assert "containment breach" in str(e)


# ── end-to-end pipeline checks ──────────────────────────────────────────────
def _full_pass_report():
    e2e = EndToEndAssurance()
    rep = AssuranceReport()
    rep.add(e2e.check_data_arrived("NVDA 10-Q", True))
    rep.add(e2e.check_model_consumed("d1", {"d1", "d2"}))
    rep.add(e2e.check_prediction_recorded("p1", {"p1"}))
    rep.add(e2e.check_api_has_prediction("p1", {"p1"}))
    rep.add(e2e.check_website_matches_db(4.8, 4.8))
    rep.add(e2e.check_no_lookahead(datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 16)))
    rep.add(e2e.check_production_locked("SIGBOT-INFLECTION-001", "gen-001", CHAMP))
    return rep


def test_full_pipeline_passes():
    assert _full_pass_report().product_trustworthy()


def test_stale_website_breaks_trust():
    e2e = EndToEndAssurance()
    rep = AssuranceReport()
    rep.add(e2e.check_website_matches_db(4.8, 3.1))   # mismatch
    assert not rep.product_trustworthy()
    assert rep.failures()[0].name == "website_matches_db"


def test_lookahead_breaks_trust():
    """Prediction BEFORE the data = look-ahead, caught end-to-end."""
    e2e = EndToEndAssurance()
    c = e2e.check_no_lookahead(datetime(2026, 1, 2), datetime(2026, 1, 1))  # pred before data
    assert c.status.value == "FAIL"


def test_missing_prediction_in_api_breaks_trust():
    e2e = EndToEndAssurance()
    c = e2e.check_api_has_prediction("p1", set())   # not in API
    assert c.status.value == "FAIL"


def test_production_unlock_detected():
    """If production is running a non-champion version, it's caught."""
    e2e = EndToEndAssurance()
    c = e2e.check_production_locked("candidate-042", "gen-002", CHAMP)
    assert c.status.value == "FAIL"


def test_empty_report_is_not_trustworthy():
    """No checks run = cannot claim trustworthy."""
    assert not AssuranceReport().product_trustworthy()
