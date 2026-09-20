"""Tests for the drawn charts and the screen's feedback loop."""
from __future__ import annotations

import numpy as np
import pytest

from sigbot.chart_svg import chart_block, chart_svg, indicators, read_chart
from sigbot.providers.market import SyntheticProvider
from sigbot.screener import (
    CRITERIA, MIN_ASSETS_FOR_LEARNING, MIN_RECORD_FOR_FEEDBACK,
    learn_weights, score_asset,
)


@pytest.fixture(scope="module")
def bars():
    return SyntheticProvider(seed=3).history("TEST", "2024-01-01", "2026-08-01")


# ------------------------------------------------------------- drawing

def test_chart_is_markup_not_script(bars):
    """The report's no-JavaScript guarantee is what makes it open on an iPhone."""
    svg = chart_svg(bars)
    assert svg.startswith("<svg") and "<script" not in svg.lower()
    assert "onload" not in svg.lower()


def test_chart_draws_every_indicator(bars):
    svg = chart_svg(bars)
    assert svg.count("<path") >= 5, "price, three averages and RSI"
    assert "<polygon" in svg, "volatility band missing"
    assert svg.count("<rect") > 50, "volume bars missing"
    assert "RSI 14" in svg


def test_short_history_degrades_without_raising():
    tiny = SyntheticProvider(seed=1).history("T", "2024-01-01", "2024-01-20")
    out = chart_svg(tiny)
    assert "Not enough history" in out and "<svg" not in out


def test_indicators_match_what_the_models_use(bars):
    ind = indicators(bars)
    for col in ("ema20", "ema50", "ema200", "bb_hi", "bb_lo", "rsi", "volume"):
        assert col in ind.columns
    assert ind["rsi"].between(0, 100).all()


# ------------------------------------------------------------- reading

def test_reading_is_plain_language(bars):
    readings = read_chart(indicators(bars))
    assert len(readings) >= 5
    joined = " ".join(r.says for r in readings).lower()
    for jargon in ("oscillator", "stochastic", "divergence", "bullish", "bearish"):
        assert jargon not in joined
    assert any("above" in r.says or "below" in r.says for r in readings)


def test_reading_calls_a_stretched_rsi_stretched(bars):
    ind = indicators(bars).copy()
    ind.loc[ind.index[-1], "rsi"] = 82.0
    says = next(r for r in read_chart(ind) if r.label.startswith("RSI")).says
    assert "Stretched" in says
    assert "weeks" in says, "an extreme reading is not a signal on its own"


def test_reading_refuses_to_forecast(bars):
    block = chart_block(bars, "TEST", "A test asset.")
    assert "None of it\n    is a forecast" in block or "is a forecast" in block
    assert "do not read charts" in block


def test_chart_block_is_script_free_and_escaped(bars):
    block = chart_block(bars, "T", '<img src=x onerror="alert(1)">')
    assert "<script" not in block.lower()
    assert 'onerror="alert(1)"' not in block and "&lt;img" in block


# --------------------------------------------------- screen feedback loop

def test_backtested_and_record_are_neutral_until_earned(bars):
    r = score_asset(bars, "T", "equity")
    assert r.scores["backtested"] == 5.0
    assert r.scores["track_record"] == 5.0
    assert "held neutral" in r.notes["backtested"]
    assert "held neutral" in r.notes["track_record"]


def test_a_thin_live_record_is_ignored(bars):
    thin = score_asset(bars, "T", "equity", record=(20, 16))
    assert thin.scores["track_record"] == 5.0, "20 checks must not move the screen"
    thick = score_asset(bars, "T", "equity", record=(200, 130))
    assert thick.scores["track_record"] > 5.0


def test_a_bad_live_record_lowers_the_score(bars):
    good = score_asset(bars, "T", "equity", record=(200, 130))
    bad = score_asset(bars, "T", "equity", record=(200, 80))
    assert bad.scores["track_record"] < good.scores["track_record"]
    assert bad.total < good.total


def test_weights_do_not_move_without_enough_assets(bars):
    results = [score_asset(bars, f"S{i}", "equity", record=(200, 130)) for i in range(5)]
    records = {f"S{i}": (200, 130) for i in range(5)}
    weights, note = learn_weights(results, records)
    assert weights == {k: w for k, (w, _) in CRITERIA.items()}
    assert str(MIN_ASSETS_FOR_LEARNING) in note
    assert "noise wearing a number" in note


def test_weights_follow_what_actually_predicted(bars):
    """Stability drives the outcome, so stability should gain weight."""
    rng = np.random.default_rng(0)
    results, records = [], {}
    for i in range(40):
        r = score_asset(bars, f"S{i}", "equity")
        r.scores["stability"] = float(i % 11)
        rate = 0.45 + 0.02 * r.scores["stability"] + rng.normal(0, 0.01)
        records[f"S{i}"] = (200, round(200 * np.clip(rate, 0, 1)))
        results.append(r)
    weights, note = learn_weights(results, records)
    assert weights["stability"] > CRITERIA["stability"][0]
    assert "corr" in note
    assert sum(weights.values()) == pytest.approx(100.0, abs=0.5)


def test_no_weight_moves_more_than_the_cap(bars):
    results, records = [], {}
    for i in range(40):
        r = score_asset(bars, f"S{i}", "equity")
        r.scores["liquidity"] = float(i % 11)
        records[f"S{i}"] = (200, 200 if i % 11 > 5 else 40)   # extreme correlation
        results.append(r)
    weights, _ = learn_weights(results, records)
    for k, (start, _) in CRITERIA.items():
        assert abs(weights[k] - start) <= 4.0, f"{k} moved too far in one cycle"


def test_min_record_threshold_is_enforced_consistently():
    assert MIN_RECORD_FOR_FEEDBACK >= 60
    assert MIN_ASSETS_FOR_LEARNING >= 25
