"""Small-cap turnover edge — the crypto market gap."""
from sigbot.small_cap_turnover import is_tradeable, turnover_edge


def test_small_cap_high_turnover_is_tradeable():
    e = turnover_edge("NEW", market_cap=50e6, daily_volume=20e6)   # 40% turnover
    assert e.tradeable and is_tradeable(e)
    assert e.bucket == "high"


def test_big_coin_is_not_in_band():
    e = turnover_edge("BTC", market_cap=1e12, daily_volume=5e10)
    assert not e.in_band and not e.tradeable


def test_dead_small_cap_is_skipped():
    e = turnover_edge("DEAD", market_cap=50e6, daily_volume=1e6)   # 2% turnover
    assert e.in_band and e.bucket == "dead" and not e.tradeable


def test_mid_turnover_is_a_watch_not_a_trade():
    e = turnover_edge("MID", market_cap=50e6, daily_volume=5e6)    # 10% turnover
    assert e.bucket == "mid" and not e.tradeable


def test_missing_data_is_safe():
    e = turnover_edge("X", market_cap=None, daily_volume=1e6)
    assert not e.tradeable
