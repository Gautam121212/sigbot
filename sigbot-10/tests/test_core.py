"""Tests that would catch the failures that actually matter.

The important one is `test_no_lookahead_by_truncation`: it does not inspect
the feature code, it re-derives every feature from a truncated history and
demands identical values. That catches a lookahead introduced by a future
edit, which code review will not.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from sigbot.backtest import walk_forward
from sigbot.decide import Gates, decide
from sigbot.features import FEATURE_COLUMNS, build_dataset, build_features, build_labels
from sigbot.providers.market import SyntheticProvider
from sigbot.providers.news import dedupe, jaccard
from sigbot.shadow import ShadowLedger
from sigbot.stats import brier_score, expected_calibration_error, wilson_interval
from sigbot.types import Article


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    return SyntheticProvider(seed=42).history("TEST", "2010-01-01", "2024-12-31")


# ----------------------------------------------------------------- leakage

def test_no_lookahead_by_truncation(prices):
    """Features at date t must not change when future bars are deleted."""
    full = build_features(prices)
    for cut in (900, 1500, 2600):
        truncated = build_features(prices.iloc[: cut + 1])
        a = full.iloc[cut][FEATURE_COLUMNS]
        b = truncated.iloc[cut][FEATURE_COLUMNS]
        pd.testing.assert_series_equal(a, b, check_names=False, rtol=1e-10, atol=1e-12)


def test_label_is_strictly_forward(prices):
    labels = build_labels(prices)
    close = prices["close"]
    for i in (10, 500, 2000):
        expected = close.iloc[i + 1] / close.iloc[i] - 1.0
        assert labels["fwd_ret"].iloc[i] == pytest.approx(expected)
    assert np.isnan(labels["fwd_ret"].iloc[-1]), "last label must be unknowable"
    assert np.isnan(labels["y_up"].iloc[-1])


def test_features_never_reference_the_label(prices):
    """Shuffling all future bars must leave past features untouched."""
    cut = 1200
    mangled = prices.copy()
    tail = mangled.iloc[cut + 1 :].sample(frac=1.0, random_state=1)
    mangled.iloc[cut + 1 :] = tail.to_numpy()
    a = build_features(prices).iloc[:cut]
    b = build_features(mangled).iloc[:cut]
    pd.testing.assert_frame_equal(a, b, rtol=1e-10, atol=1e-12)


# ------------------------------------------------------------- calibration

def test_wilson_shrinks_with_evidence():
    thin_lo, _ = wilson_interval(8, 10)
    thick_lo, _ = wilson_interval(800, 1000)
    assert thin_lo < 0.60, "10 samples must not support a confident claim"
    assert thick_lo > 0.77
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_never_exceeds_point_estimate():
    for k, n in [(1, 3), (17, 40), (450, 900)]:
        lo, hi = wilson_interval(k, n)
        assert lo <= k / n <= hi


def test_ece_zero_for_perfect_calibration():
    rng = np.random.default_rng(3)
    p = rng.uniform(0.05, 0.95, 40000)
    y = (rng.uniform(size=p.size) < p).astype(float)
    assert expected_calibration_error(p, y) < 0.02
    assert brier_score(p, y) < brier_score(np.full_like(p, 0.5), y) + 1e-9


# ---------------------------------------------------------------- decision

SKILLED = 0.01  # a model that has demonstrated out-of-fold skill


def test_thin_calibration_bin_forces_hold():
    d = decide(p_up=0.95, p_up_lower=0.94, p_dn_lower=0.0, expected_move=0.05,
               bin_n=3, base_rate=0.52, gates=Gates(), model_skill=SKILLED)
    assert d.side == "HOLD"
    assert any("calibration support" in b for b in d.blocked_by)


def test_edge_inside_costs_forces_hold():
    d = decide(p_up=0.80, p_up_lower=0.75, p_dn_lower=0.0, expected_move=0.0005,
               bin_n=500, base_rate=0.52, gates=Gates(cost_pct=0.0010),
               model_skill=SKILLED)
    assert d.side == "HOLD"


def test_skilless_model_cannot_trade_however_confident():
    """The gate that the null test forced into existence."""
    for skill in (float("nan"), -0.02, 0.0):
        d = decide(p_up=0.99, p_up_lower=0.97, p_dn_lower=0.0, expected_move=0.08,
                   bin_n=5000, base_rate=0.52, gates=Gates(), model_skill=skill)
        assert d.side == "HOLD"
        assert any("no out-of-fold skill" in b for b in d.blocked_by)


def test_clear_case_produces_buy():
    d = decide(p_up=0.72, p_up_lower=0.66, p_dn_lower=0.05, expected_move=0.012,
               bin_n=300, base_rate=0.53, gates=Gates(), model_skill=SKILLED)
    assert d.side == "BUY" and d.reasons


# -------------------------------------------------------------- null model

def test_no_edge_on_random_walk(prices):
    """The system must NOT find edge in data that has none.

    A pipeline that reports a profitable signal here has a leak. This is the
    single most informative test in the suite.
    """
    res = walk_forward(build_dataset(prices), symbol="RANDOM")
    assert res.n_predictions > 1000
    # Brier skill over the base rate must be ~0, and is allowed to be negative.
    skill = res.brier_baseline - res.brier
    assert skill < 0.005, f"found skill {skill:.4f} in a random walk — leak suspected"
    rate = res.n_signals / res.n_predictions
    assert rate < 0.005, f"{rate:.3%} of days signalled on a random walk — gates too loose"
    if res.n_signals >= 30:
        assert res.signal_hit_lower < 0.60, "confident hit rate on noise implies a leak"


# ------------------------------------------------------------------- news

def _article(uid: str, title: str, source: str, minutes: int) -> Article:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    return Article(uid, title, "", f"http://x/{uid}", source,
                   now + timedelta(minutes=minutes), now)


def test_syndicated_stories_collapse_to_one_cluster():
    arts = [
        _article("a", "Nvidia beats earnings estimates on AI demand", "Reuters", 0),
        _article("b", "Nvidia beats earnings estimates on strong AI demand", "CNBC", 5),
        _article("c", "Nvidia earnings beat estimates as AI demand stays strong", "WSJ", 9),
        _article("d", "Bitcoin ETF sees record weekly inflows", "CoinDesk", 20),
    ]
    clusters = dedupe(arts)
    assert len(clusters) == 2
    biggest = max(clusters, key=len)
    assert len(biggest) == 3
    assert biggest[0].source == "Reuters", "earliest publisher must lead the cluster"


def test_jaccard_bounds():
    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0


# ----------------------------------------------------------------- ledger

def test_ledger_roundtrip(tmp_path):
    led = ShadowLedger(tmp_path / "t.db")
    win = led.record("daily", "AAPL", "BUY", 0.62, 0.01, 100.0, horizon_hours=-1)
    loss = led.record("daily", "AAPL", "BUY", 0.61, 0.01, 100.0, horizon_hours=-1)
    assert len(led.due("daily")) == 2
    led.resolve(win, 103.0)
    led.resolve(loss, 97.0)
    n, hit, lo = led.overall("daily")
    assert (n, hit) == (2, 0.5)
    assert lo < 0.5, "two observations cannot support a confident hit rate"
    assert led.due("daily") == []


def test_short_side_scores_inverted(tmp_path):
    led = ShadowLedger(tmp_path / "s.db")
    pid = led.record("news", "BTC-USD", "SELL", -0.5, None, 100.0, horizon_hours=-1)
    led.resolve(pid, 95.0)
    assert led.overall("news")[1] == 1.0


def test_hit_and_outcome_mode_agree(tmp_path):
    """A move too small to cover costs is not a win.

    `hit` was taken from the gross sign while `outcome_mode` was net of costs,
    so a +0.05% move scored as a win in every hit rate and as `magnitude_short`
    in the breakdown. That inflated every rate in the system.
    """
    import sqlite3

    from sigbot.shadow import ShadowLedger
    from sigbot.tiers import Failure

    led = ShadowLedger(tmp_path / "s.db")
    cases = [
        ("below costs", 100.05, 100.0, 100.1, 99.9, Failure.MAGNITUDE_SHORT, 0),
        ("real win", 103.0, 100.0, 103.5, 99.8, Failure.WIN, 1),
        ("wrong way", 97.0, 100.0, 100.2, 97.0, Failure.DIRECTION_WRONG, 0),
        ("reversal", 98.5, 100.0, 101.5, 98.0, Failure.REVERSAL, 0),
    ]
    for label, close, op, hi, lo, _mode, _hit in cases:
        pid = led.record("daily", label, "BUY", 0.6, 0.02, 100.0, horizon_hours=-1)
        led.resolve(pid, close, bar_open=op, bar_high=hi, bar_low=lo)

    with sqlite3.connect(tmp_path / "s.db") as con:
        rows = {s: (h, m) for s, h, m in
                con.execute("SELECT symbol, hit, outcome_mode FROM predictions")}

    for label, _c, _o, _h, _l, mode, hit in cases:
        got_hit, got_mode = rows[label]
        assert got_mode == mode.value, f"{label}: mode {got_mode}"
        assert got_hit == hit, f"{label}: hit {got_hit}, expected {hit}"
        assert (got_hit == 1) == (got_mode == Failure.WIN.value), (
            f"{label}: hit and outcome_mode disagree")
