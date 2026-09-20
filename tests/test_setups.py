"""The evidence bar is the whole point — it must not be easy to clear."""
from __future__ import annotations

from sigbot.setups import SETUPS, EraResult, Setup, evaluate


def _setup(eras, name="x", side="BUY"):
    return Setup(name=name, side=side, plain="p",
                 condition=lambda row: True, eras=tuple(eras))


def test_one_good_era_is_not_evidence():
    """Any sufficiently searched dataset yields one good window."""
    single = _setup([EraResult("A", 500, 60.0, 47.0)])
    assert not single.is_validated()


def test_a_setup_that_failed_in_any_era_is_rejected():
    """A setup that worked hugely once and failed twice has an attractive
    average and no future. Averaging would hide exactly that."""
    mixed = _setup([
        EraResult("A", 100, 70.0, 47.0),   # +23pp
        EraResult("B", 100, 44.0, 47.0),   # -3pp
        EraResult("C", 100, 45.0, 47.0),   # -2pp
    ])
    assert mixed.measured_edge_pp > 3.0, "the average alone looks fine"
    assert not mixed.is_validated(), "but one bad era must disqualify it"


def test_a_consistent_small_edge_is_accepted():
    good = _setup([
        EraResult("A", 80, 55.0, 47.0),
        EraResult("B", 90, 56.0, 48.0),
        EraResult("C", 80, 54.0, 47.0),
    ])
    assert good.is_validated()


def test_a_tiny_consistent_edge_is_still_rejected():
    """Consistency is necessary, not sufficient — +0.5pp does not pay costs."""
    thin = _setup([
        EraResult("A", 500, 47.5, 47.0),
        EraResult("B", 500, 48.4, 48.0),
        EraResult("C", 500, 47.6, 47.4),
    ])
    assert all(e.edge_pp > 0 for e in thin.eras)
    assert not thin.is_validated()


def test_the_shipped_setup_carries_its_evidence():
    """The era results live in the code so the claim can be audited."""
    for setup in SETUPS:
        assert setup.eras, f"{setup.name} claims an edge with no evidence"
        for era in setup.eras:
            assert era.n > 0 and 0 <= era.hit_pct <= 100


def test_silence_is_the_normal_answer():
    """A setup fired on roughly one session in 170. Rarity is the design."""
    assert evaluate({"rsi_14": 50.0}) is None
    assert evaluate({"rsi_14": 25.0}) is None, "RSI<30 is NOT the validated bar"
    assert evaluate({}) is None, "missing data must never fire a trade"
    assert evaluate({"rsi_14": None}) is None


def test_the_validated_threshold_is_twenty_not_thirty():
    """At RSI<30 the edge is +2.0pp and inconsistent across eras; at RSI<20 it
    is +9.7pp and present in all three."""
    fired = evaluate({"rsi_14": 19.0})
    assert fired is not None and fired.name == "deep-oversold"
