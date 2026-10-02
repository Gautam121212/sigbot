"""Research & innovation engine — innovation unlimited, promotion brutal."""
from sigbot.research_innovation_engine import (
    Component, ComponentRole, Hypothesis, InnovationLedger, IntegrityScreen,
    InventionMethod, PromotionGate, PromotionVerdict, ValidatedLibrary,
    corrected_t_bar)


def _hyp(hid="h"):
    return Hypothesis(hid, (Component("x", ComponentRole.ENTRY),),
                      InventionMethod.RECOMBINATION)


# ── the spine: correction sized to TOTAL generated ──────────────────────────
def test_bar_rises_with_total_generated():
    assert corrected_t_bar(1) < corrected_t_bar(100) < corrected_t_bar(1000)
    assert corrected_t_bar(1000) > 4.0        # much stricter than 1.96


def test_candidate_passing_naive_bar_fails_total_count_bar():
    """t=2.5 passes 1.96 alone but fails when it's 1 of 1000 generated."""
    innov = InnovationLedger()
    for i in range(1000):
        innov.record_generated(_hyp(f"h{i}"))
    gate = PromotionGate(innov)
    v = gate.promote(_hyp("cand"), oos_edge=2.0, oos_mean=2.5, oos_std=20,
                     oos_n=400, correlation_with_library=0.1)
    assert v == PromotionVerdict.REJECTED_CORRECTION


def test_strong_candidate_clears_even_large_count():
    innov = InnovationLedger()
    for i in range(1000):
        innov.record_generated(_hyp(f"h{i}"))
    gate = PromotionGate(innov)
    v = gate.promote(_hyp("cand"), oos_edge=3.0, oos_mean=4.5, oos_std=20,
                     oos_n=400, correlation_with_library=0.1)
    assert v == PromotionVerdict.PROMOTED


def test_count_is_permanent_cannot_be_reset():
    """The total count can only grow — you can't make the bar easier."""
    innov = InnovationLedger()
    innov.record_generated(_hyp("a"))
    innov.record_generated(_hyp("b"))
    assert innov.total_generated() == 2
    assert not hasattr(innov, "reset")
    assert not hasattr(innov, "clear_count")


# ── promotion rejects redundant and no-edge ─────────────────────────────────
def test_redundant_candidate_rejected():
    innov = InnovationLedger()
    innov.record_generated(_hyp())
    gate = PromotionGate(innov)
    v = gate.promote(_hyp(), oos_edge=3.0, oos_mean=5.0, oos_std=20, oos_n=400,
                     correlation_with_library=0.8)   # high corr
    assert v == PromotionVerdict.REJECTED_REDUNDANT


def test_no_oos_edge_rejected():
    innov = InnovationLedger()
    innov.record_generated(_hyp())
    gate = PromotionGate(innov)
    v = gate.promote(_hyp(), oos_edge=-0.5, oos_mean=1.0, oos_std=20, oos_n=400,
                     correlation_with_library=0.1)
    assert v == PromotionVerdict.REJECTED_OOS


# ── the permissive first gate ───────────────────────────────────────────────
def test_integrity_screen_is_permissive_on_weak_edge():
    """A weak-but-real signal passes the first gate to be dissected."""
    s = IntegrityScreen(has_lookahead=False, sample_size=400,
                        cost_sensitivity_catastrophic=False, behaves_randomly=False)
    assert s.passes()


def test_integrity_screen_kills_lookahead():
    s = IntegrityScreen(has_lookahead=True, sample_size=400,
                        cost_sensitivity_catastrophic=False, behaves_randomly=False)
    assert not s.passes()


def test_integrity_screen_kills_tiny_sample():
    s = IntegrityScreen(has_lookahead=False, sample_size=5,
                        cost_sensitivity_catastrophic=False, behaves_randomly=False)
    assert not s.passes()


# ── hypothesis is never self-validating ─────────────────────────────────────
def test_hypothesis_has_no_truth_value():
    h = _hyp()
    assert not hasattr(h, "is_valid")
    assert not hasattr(h, "edge")
    assert not hasattr(h, "promote")


# ── failure learning ────────────────────────────────────────────────────────
def test_failure_learning_records_why_not_just_that():
    innov = InnovationLedger()
    innov.record_failure_mode("rsi_overbought", "no incremental value here")
    innov.record_failure_mode("large_position", "fails on capacity")
    assert innov.failure_lesson("rsi_overbought") == "no incremental value here"
    assert "capacity" in innov.failure_lesson("large_position")


def test_component_track_record_accumulates():
    innov = InnovationLedger()
    innov.record_component_result("volume_shock", 2.0)
    innov.record_component_result("volume_shock", -1.0)
    tr = innov.component_track_record("volume_shock")
    assert tr["n"] == 2
    assert tr["times_positive"] == 1


# ── promotion rate is tiny ──────────────────────────────────────────────────
def test_promotion_rate_is_tiny():
    innov = InnovationLedger()
    for i in range(1000):
        innov.record_generated(_hyp(f"h{i}"))
    lib = ValidatedLibrary()
    lib.add("one_survivor")
    assert lib.promotion_rate(innov.total_generated()) == 0.001
