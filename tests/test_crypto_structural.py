"""Crypto structural edge — basis/OI/spread, the non-directional edge."""
from sigbot.crypto_structural import is_tradeable, structural_edge


def test_crowded_shorts_negative_basis_is_a_buy():
    e = structural_edge("HEMI", basis_pct=-9.79, open_interest=139580, spread_pct=0.017)
    assert e.side == "BUY" and is_tradeable(e)


def test_crowded_longs_positive_basis_is_a_sell():
    e = structural_edge("X", basis_pct=5.0, open_interest=20000, spread_pct=0.1)
    assert e.side == "SELL"


def test_illiquid_coin_is_skipped():
    e = structural_edge("BANANA", basis_pct=8.73, open_interest=702, spread_pct=0.023)
    assert e.side == "skip" and not is_tradeable(e)


def test_wide_spread_is_skipped():
    e = structural_edge("Y", basis_pct=10.0, open_interest=20000, spread_pct=2.0)
    assert e.side == "skip"


def test_small_basis_is_neutral():
    e = structural_edge("BTC", basis_pct=0.05, open_interest=6103, spread_pct=0.001)
    assert e.side == "neutral" and not is_tradeable(e)
