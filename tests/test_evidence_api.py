"""Evidence/status API — one state surface, append-only history, fail-closed."""
import pytest

from sigbot.canonical_evidence import EvidenceFact, EvidenceState
from sigbot.evidence_api import (
    EvidenceAPI, EvidenceHistory, build_history_from_store)
from sigbot.canonical_evidence import build_canonical_store


# ── append-only history ─────────────────────────────────────────────────────
def test_history_keeps_every_version():
    h = EvidenceHistory()
    h.append(EvidenceFact("k", "1", EvidenceState.BACKTEST, "a", "2026"))
    h.append(EvidenceFact("k", "2", EvidenceState.PAPER, "b", "2027"))
    assert len(h.history_of("k")) == 2          # nothing overwritten


def test_history_current_is_latest():
    h = EvidenceHistory()
    h.append(EvidenceFact("k", "1", EvidenceState.BACKTEST, "a", "2026"))
    h.append(EvidenceFact("k", "2", EvidenceState.PAPER, "b", "2027"))
    assert h.current("k").value == "2"


def test_state_timeline_tracks_evolution():
    h = EvidenceHistory()
    h.append(EvidenceFact("k", "1", EvidenceState.BACKTEST, "a", "2026"))
    h.append(EvidenceFact("k", "2", EvidenceState.PAPER, "b", "2027"))
    h.append(EvidenceFact("k", "3", EvidenceState.LIVE, "c", "2027"))
    assert h.state_timeline("k") == ["backtest", "paper", "live"]


def test_history_ids_are_unique_and_immutable():
    h = EvidenceHistory()
    id1 = h.append(EvidenceFact("a", "1", EvidenceState.BACKTEST, "s", "2026"))
    id2 = h.append(EvidenceFact("b", "2", EvidenceState.BACKTEST, "s", "2026"))
    assert id1 != id2
    assert id1.startswith("FACT-")


# ── API serves finished facts, never recalculates ──────────────────────────
def test_get_fact_serves_label_and_state():
    api = EvidenceAPI()
    f = api.get_fact("inflection.net_per_trade")
    assert f.value == "+6.57%"
    assert f.evidence_state == "backtest"
    assert f.label == "BACKTEST"


def test_get_fact_raises_on_untraceable():
    api = EvidenceAPI()
    with pytest.raises(KeyError):
        api.get_fact("fake.secret_number")


def test_fact_payload_has_no_calculation_methods():
    """The payload is data only — the frontend can't recompute from it."""
    api = EvidenceAPI()
    f = api.get_fact("inflection.sharpe")
    assert not hasattr(f, "recalculate")
    assert not hasattr(f, "relabel")


# ── evidence endpoint is honest about forward state ─────────────────────────
def test_evidence_reports_no_live_yet():
    api = EvidenceAPI()
    ev = api.evidence()
    assert not ev.has_live
    assert not ev.has_paper
    assert "No forward" in ev.honest_note


def test_evidence_counts_match_store():
    api = EvidenceAPI()
    ev = api.evidence()
    assert ev.state_counts["backtest"] == 8
    assert ev.state_counts["oos"] == 2
    assert ev.state_counts["live"] == 0


# ── status is fail-closed ───────────────────────────────────────────────────
def test_status_allows_capital_when_healthy():
    api = EvidenceAPI()
    st = api.status({"data": "OK", "website": "OK"}, safe=True)
    assert st.capital_authorization == "ALLOWED"


def test_status_blocks_on_pipeline_failure():
    api = EvidenceAPI()
    st = api.status({"data": "OK", "website": "FAIL"}, safe=True)
    assert st.capital_authorization == "BLOCKED"


def test_status_blocks_when_unsafe():
    api = EvidenceAPI()
    st = api.status({"data": "OK"}, safe=False)
    assert st.capital_authorization == "BLOCKED"


# ── forward facts enter only through the guarded path ───────────────────────
def test_record_forward_fact_appends_and_registers():
    api = EvidenceAPI()
    before = api.history.state_timeline("inflection.net_per_trade")
    api.record_forward_fact(EvidenceFact(
        "inflection.net_per_trade", "+5.1%", EvidenceState.PAPER,
        "paper_run_2027Q1", "2027-03"))
    after = api.history.state_timeline("inflection.net_per_trade")
    assert after == before + ["paper"]
    # the store now reflects the upgraded state
    assert api.store.require("inflection.net_per_trade").state == EvidenceState.PAPER


def test_record_forward_fact_blocks_relabel():
    """Can't launder a backtest number to live via the API either."""
    from sigbot.canonical_evidence import StateUpgradeError
    api = EvidenceAPI()
    with pytest.raises(StateUpgradeError):
        api.record_forward_fact(EvidenceFact(
            "inflection.net_per_trade", "+6.57%", EvidenceState.LIVE,
            "trade_level_backtest", "2026"))   # same source = laundering


# ── one surface: both consumers get identical facts ─────────────────────────
def test_marketing_and_dashboard_get_same_fact():
    api = EvidenceAPI()
    marketing_view = api.get_fact("inflection.win_rate")
    dashboard_view = api.get_fact("inflection.win_rate")
    assert marketing_view == dashboard_view       # one source, no drift


def test_history_seeded_from_store():
    store = build_canonical_store()
    h = build_history_from_store(store)
    assert len(h.all_entries()) == len(store.all_keys())
