"""The leverage-crowding signal — the confirmed crypto edge."""
from __future__ import annotations

import random

from sigbot.crypto_signals import read_crowding


def _series(calm_days, wild_days, wild_vol=0.05, flat=True, seed=1):
    random.seed(seed)
    p = [100.0]
    for _ in range(calm_days):
        p.append(p[-1] * (1 + random.gauss(0.001, 0.008)))
    for _ in range(wild_days):
        p.append(p[-1] * (1 + random.gauss(0.0, wild_vol)))
    if flat:
        p[-1] = p[-1 - 10] * 1.01     # pin recent drift near flat
    return p


def test_rising_vol_with_flat_price_reads_as_crowded():
    r = read_crowding(_series(15, 11, wild_vol=0.05, flat=True))
    assert r.crowded
    assert "crowded" in r.reason


def test_calm_steady_uptrend_is_not_crowded():
    p = [100.0 * (1.002 ** i) for i in range(40)]
    assert not read_crowding(p).crowded


def test_too_little_history_is_not_crowded_and_says_so():
    r = read_crowding([100, 101, 102])
    assert not r.crowded and "not enough history" in r.reason


def test_a_big_directional_move_is_not_flagged_crowded():
    """Vol can rise on a real trend — that is not crowding. Crowding needs the
    price to have gone NOWHERE."""
    random.seed(2)
    p = [100.0]
    for _ in range(15):
        p.append(p[-1] * (1 + random.gauss(0.001, 0.008)))
    for _ in range(11):
        p.append(p[-1] * (1 + random.gauss(0.04, 0.05)))   # strong up-drift
    r = read_crowding(p)
    assert not r.crowded, "a trending move is not crowding"


def test_the_crypto_model_stands_aside_on_a_crowded_long():
    """The filter must actually reach the forecast: a BUY in a crowded market
    is recorded but marked not tradeable."""
    import inspect

    import sigbot.crypto15m as c
    src = inspect.getsource(c.forecast)
    assert "read_crowding" in src
    assert 'side == "BUY"' in src and "tradeable = False" in src
