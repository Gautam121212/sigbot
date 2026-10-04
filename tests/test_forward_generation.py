"""Forward Generation — the immutable freeze baseline."""
import pytest

from sigbot.forward_generation import (
    ForwardGeneration, GenerationRegistry, GenerationViolation)


def _gen(gid="FWD-GEN-001", stocks="inflection-v1"):
    return ForwardGeneration.create(
        generation_id=gid, git_commit="35b82e1",
        model_versions={"stocks": stocks, "news": "v1"},
        trader_policy_version="tp-v1", governor_policy_version="gov-v1",
        risk_budget_rung="OOS_PROVEN_SIGNAL",
        execution_assumptions={"cost_bps": 30, "fill": "next_open"},
        research_library_hash="abc")


def _state(stocks="inflection-v1"):
    return dict(git_commit="35b82e1",
                model_versions={"stocks": stocks, "news": "v1"},
                trader_policy_version="tp-v1", governor_policy_version="gov-v1",
                risk_budget_rung="OOS_PROVEN_SIGNAL",
                execution_assumptions={"cost_bps": 30, "fill": "next_open"},
                research_library_hash="abc")


def test_generation_seals_a_hash():
    g = _gen()
    assert g.frozen_hash != ""
    assert g.generation_id == "FWD-GEN-001"


def test_same_state_matches():
    g = _gen()
    assert g.matches(**_state())


def test_model_change_breaks_match():
    g = _gen()
    assert not g.matches(**_state(stocks="inflection-v2"))


def test_policy_change_breaks_match():
    g = _gen()
    st = _state()
    st["trader_policy_version"] = "tp-v2"
    assert not g.matches(**st)


def test_execution_assumption_change_breaks_match():
    g = _gen()
    st = _state()
    st["execution_assumptions"] = {"cost_bps": 10, "fill": "next_open"}
    assert not g.matches(**st)


def test_registry_active_is_newest():
    reg = GenerationRegistry()
    reg.open_generation(_gen("FWD-GEN-001"))
    reg.open_generation(_gen("FWD-GEN-002"))
    assert reg.active().generation_id == "FWD-GEN-002"


def test_duplicate_generation_rejected():
    reg = GenerationRegistry()
    reg.open_generation(_gen("FWD-GEN-001"))
    with pytest.raises(ValueError):
        reg.open_generation(_gen("FWD-GEN-001"))


def test_verify_passes_when_unchanged():
    reg = GenerationRegistry()
    reg.open_generation(_gen())
    reg.verify_current_matches_active(**_state())   # no raise


def test_verify_raises_on_drift():
    reg = GenerationRegistry()
    reg.open_generation(_gen())
    with pytest.raises(GenerationViolation):
        reg.verify_current_matches_active(**_state(stocks="inflection-v2"))


def test_verify_raises_with_no_active():
    reg = GenerationRegistry()
    with pytest.raises(GenerationViolation):
        reg.verify_current_matches_active(**_state())


def test_old_generation_retrievable_after_new_opened():
    reg = GenerationRegistry()
    reg.open_generation(_gen("FWD-GEN-001", stocks="inflection-v1"))
    reg.open_generation(_gen("FWD-GEN-002", stocks="inflection-v2"))
    # the old generation is immutable and still retrievable
    old = reg.get("FWD-GEN-001")
    assert old.model_versions["stocks"] == "inflection-v1"
