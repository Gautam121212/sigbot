"""No row is ever recorded as two forecasts — the collision resolver.

The user's most important requirement: the new signals must not collide with
the existing ones. Candidates may OVERLAP (several could fire on one row), but
scan_row must resolve to exactly ONE, deterministically.
"""
from __future__ import annotations

import random

from sigbot.crypto_signals import below_ma7_dip, low_volume_drop_reversal
from sigbot.scan import CANDIDATES, _hammer_in_downtrend, _oversold_money_holding, scan_row


def _row(**kw):
    base = {"close": 100.0, "prev_close": 99.0, "rsi_14": 50.0, "mfi_14": 50.0,
            "sma_200": 110.0, "sma_50": 105.0, "willr_14": -50.0, "hi52": 120.0,
            "volume": 2e6, "volume_ma_20": 2e6, "index_up": True,
            "index_regime": "down/volatile", "price_change_10d": 0.0,
            "obv_rising": False, "cdl_hammer": 0.0}
    base.update(kw)
    return base


def test_scan_row_always_returns_at_most_one_signal():
    """Fuzz many rows; scan_row must never be ambiguous — one Hit or None."""
    random.seed(7)
    for _ in range(5000):
        row = _row(rsi_14=random.uniform(5, 95), willr_14=random.uniform(-100, 0),
                   price_change_10d=random.uniform(-0.15, 0.10),
                   obv_rising=random.choice([True, False]),
                   cdl_hammer=random.choice([0.0, 1.0]),
                   close=100.0, sma_200=random.uniform(80, 130),
                   index_regime=random.choice(["up/calm", "down/volatile",
                                               "up/volatile", "down/calm"]))
        hit = scan_row("AAPL", row)
        # Either None or exactly one named candidate — never a list.
        assert hit is None or hasattr(hit, "candidate")


def test_the_pick_is_deterministic():
    """The same row always resolves to the same signal — no run-to-run drift."""
    row = _row(rsi_14=30.0, cdl_hammer=1.0, price_change_10d=-0.05, obv_rising=True)
    picks = {scan_row("AAPL", row).candidate.name for _ in range(20)}
    assert len(picks) == 1


def test_hammer_and_oversold_money_never_both_fire():
    """Guard by construction: hammer owns RSI 20-40, oversold-money owns <20."""
    for rsi in (10, 15, 19, 20, 25, 35, 39, 40, 50):
        row = _row(rsi_14=rsi, mfi_14=12.0, cdl_hammer=1.0)
        assert not (_hammer_in_downtrend(row) and _oversold_money_holding(row)), rsi


def test_crypto_ma7_dip_yields_to_low_volume_drop():
    """The two crypto mean-reversion signals never both claim one bar."""
    closes = [100.0] * 20 + [100.0, 96.0]        # -4% last day
    volumes = [1000.0] * 20 + [1000.0, 500.0]     # low volume
    assert low_volume_drop_reversal(closes, volumes)[0]
    assert not below_ma7_dip(closes, volumes)[0], "ma7 dip must defer"


def test_all_candidate_names_are_unique():
    names = [c.name for c in CANDIDATES]
    assert len(names) == len(set(names))
