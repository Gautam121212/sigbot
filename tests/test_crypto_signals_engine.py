"""Crypto move-detection engine — volume/news precursors of a move."""
from sigbot.crypto_signals_engine import detect_move, is_move_imminent


def test_two_precursors_flag_an_imminent_move():
    w = detect_move("BTC", volume_ratio=3.0, range_ratio=2.0)
    assert w.imminent and is_move_imminent(w)
    assert w.precursors == 2


def test_one_precursor_is_a_watch_not_a_signal():
    w = detect_move("ETH", volume_ratio=3.0, range_ratio=1.0)
    assert not w.imminent and w.precursors == 1


def test_quiet_market_no_precursors():
    w = detect_move("SOL", volume_ratio=1.1, range_ratio=1.0,
                    attention_ratio=1.0, basis_change_pct=0.1)
    assert not w.imminent and w.precursors == 0


def test_all_four_precursors_stack():
    w = detect_move("BTC", volume_ratio=3.0, range_ratio=2.0,
                    attention_ratio=2.5, basis_change_pct=1.0)
    assert w.precursors == 4 and w.imminent


def test_it_is_direction_agnostic():
    """The engine flags that a move is COMING, not which way."""
    w = detect_move("BTC", volume_ratio=3.0, range_ratio=2.0)
    assert "direction uncertain" in w.note
