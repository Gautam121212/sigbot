"""Canonical evidence store — one traceable source, no hand-typed figures."""
import pytest

from sigbot.canonical_evidence import (
    CanonicalEvidenceStore, EvidenceFact, EvidenceState, StateUpgradeError,
    build_canonical_store)


def _fact(key="k", value="1", state=EvidenceState.BACKTEST, src="src"):
    return EvidenceFact(key, value, state, src, "2026")


# ── every fact carries provenance ───────────────────────────────────────────
def test_fact_requires_value_state_source():
    f = _fact()
    assert f.value and f.state and f.source_finding


def test_label_includes_state():
    assert _fact(state=EvidenceState.OOS).label() == "OOS"


def test_label_includes_caveat():
    f = EvidenceFact("k", "1", EvidenceState.PROVISIONAL, "s", "2026",
                     caveat="45d PIT delay")
    assert "PROVISIONAL" in f.label() and "45d" in f.label()


# ── untraceable figures cannot render ───────────────────────────────────────
def test_require_raises_on_unregistered_key():
    s = CanonicalEvidenceStore()
    with pytest.raises(KeyError):
        s.require("does.not.exist")


def test_get_returns_none_for_missing():
    assert CanonicalEvidenceStore().get("x") is None


# ── no silent backtest -> live relabel (the laundering case) ─────────────────
def test_cannot_upgrade_state_from_same_source():
    s = CanonicalEvidenceStore()
    s.register(_fact("inflection.ret", "6.57", EvidenceState.BACKTEST, "bt"))
    with pytest.raises(StateUpgradeError):
        s.register(_fact("inflection.ret", "6.57", EvidenceState.LIVE, "bt"))


def test_genuine_new_forward_evidence_accepted():
    """A real forward measurement (different source) legitimately upgrades state."""
    s = CanonicalEvidenceStore()
    s.register(_fact("inflection.ret", "6.57", EvidenceState.BACKTEST, "bt"))
    s.register(_fact("inflection.ret", "5.1", EvidenceState.PAPER, "paper_fwd"))
    assert s.require("inflection.ret").state == EvidenceState.PAPER


def test_same_state_replacement_allowed():
    s = CanonicalEvidenceStore()
    s.register(_fact("k", "1", EvidenceState.BACKTEST, "src"))
    s.register(_fact("k", "2", EvidenceState.BACKTEST, "src"))   # update value
    assert s.require("k").value == "2"


# ── the canonical set is honest about forward state ─────────────────────────
def test_canonical_store_has_no_live_yet():
    s = build_canonical_store()
    assert not s.has_any_live()
    assert len(s.facts_by_state(EvidenceState.LIVE)) == 0
    assert len(s.facts_by_state(EvidenceState.PAPER)) == 0


def test_inflection_figures_are_historical_reported_not_live():
    """The 1,703-trade result is HISTORICAL_REPORTED — the generating harness did
    not survive in the repo, so it is retained for provenance but excluded from
    qualification. Never LIVE, never even BACKTEST (a backtest is reproducible)."""
    s = build_canonical_store()
    assert (s.require("inflection.net_per_trade").state
            == EvidenceState.HISTORICAL_REPORTED)
    assert (s.require("inflection.forward_cagr").state
            == EvidenceState.HISTORICAL_REPORTED)
    # and it must not count toward qualification
    assert not s.require("inflection.net_per_trade").state.counts_for_qualification()


def test_scenario_map_is_provisional():
    s = build_canonical_store()
    f = s.require("scenario.stress_edge")
    assert f.state == EvidenceState.PROVISIONAL
    assert "PIT" in f.label()


def test_every_canonical_fact_has_a_source():
    s = build_canonical_store()
    for key in s.all_keys():
        assert s.require(key).source_finding        # non-empty


# ── the marketing numbers all come from the store ───────────────────────────
def test_marketing_figures_are_all_registered():
    """The exact figures the homepage shows must exist in the canonical store."""
    s = build_canonical_store()
    for key in ("inflection.trades", "inflection.net_per_trade",
                "inflection.win_rate", "inflection.sharpe",
                "inflection.forward_cagr", "inflection.walk_forward",
                "research.hypotheses_tested", "research.survived",
                "research.public_no_edge", "research.public_additive"):
        assert s.get(key) is not None, f"{key} missing from canonical store"


def test_forward_state_is_not_faked():
    """A future-upgrade is forbidden to synthesize a LIVE number not measured."""
    s = build_canonical_store()
    # there is no path that produces a LIVE inflection figure without a live source
    assert s.require("inflection.net_per_trade").state != EvidenceState.LIVE
