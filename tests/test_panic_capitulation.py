"""The panic-capitulation signal — the edge that only looked broken."""
from sigbot.scan import CANDIDATES, _panic_capitulation


def test_panic_capitulation_needs_acceleration():
    base = {"willr_14": -95, "index_regime": "down/volatile"}
    assert not _panic_capitulation(base)                    # no acceleration flag
    assert _panic_capitulation({**base, "index_accelerating": True})


def test_panic_capitulation_only_in_a_volatile_decline():
    row = {"willr_14": -95, "index_regime": "up/calm", "index_accelerating": True}
    assert not _panic_capitulation(row)


def test_it_is_registered_and_held_five_days():
    c = next(c for c in CANDIDATES if c.name == "panic-capitulation")
    assert c.hold_days == 5                # faster modern rebound
    assert c.eras_positive == 3            # held every period in absolute terms
