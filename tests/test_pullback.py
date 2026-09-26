"""The pullback-in-uptrend signal — the Connors gap the factor comparison found."""
from sigbot.scan import CANDIDATES, _panic_capitulation, _pullback_in_uptrend


def test_three_down_days_above_200ma_fires():
    row = {"close": 110, "sma_200": 100, "consecutive_down_days": 3}
    assert _pullback_in_uptrend(row)


def test_below_200ma_does_not_fire():
    """It's a pullback in an UPtrend — below the 200MA it must not fire."""
    row = {"close": 90, "sma_200": 100, "consecutive_down_days": 3}
    assert not _pullback_in_uptrend(row)


def test_fewer_than_three_down_days_does_not_fire():
    row = {"close": 110, "sma_200": 100, "consecutive_down_days": 2}
    assert not _pullback_in_uptrend(row)


def test_no_overlap_with_capitulation():
    """Pullback needs uptrend (close>200MA); capitulation needs down/volatile.
    They cannot both fire on one row."""
    row = {"close": 110, "sma_200": 100, "consecutive_down_days": 3,
           "willr_14": -95, "index_regime": "up/calm"}
    assert _pullback_in_uptrend(row)
    assert not _panic_capitulation(row)


def test_it_is_registered_as_reversion_held_five_days():
    c = next(c for c in CANDIDATES if c.name == "pullback-in-uptrend")
    assert c.style == "reversion" and c.hold_days == 5
    assert c.eras_positive == 3
