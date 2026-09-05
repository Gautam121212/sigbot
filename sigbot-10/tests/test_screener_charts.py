"""Tests for the screen and the chart links."""
from __future__ import annotations

import numpy as np
import pytest

from sigbot.charts import STUDIES, chart_url, indicator_note, tv_symbol, write_charts_page
from sigbot.providers.market import SyntheticNetworkProvider
from sigbot.screener import CRITERIA, MIN_BARS, explain, screen, score_asset, select
from sigbot.watchlist import RULES


@pytest.fixture(scope="module")
def panel():
    return SyntheticNetworkProvider(
        anchors=["ANCH1", "ANCH2"], couplings={"DEP1": ("ANCH1", 0.40)},
        independents=[f"IND{i}" for i in range(10)], n_days=1600, seed=5)


def _kinds(bars):
    return {k: ("crypto" if k.startswith("IND") else "equity") for k in bars}


# ------------------------------------------------------------- screening

def test_weights_sum_to_one_hundred():
    assert sum(w for w, _ in CRITERIA.values()) == pytest.approx(100.0)


def test_a_linked_asset_screens_highest(panel):
    """The screen should find the asset that actually follows an anchor."""
    bars = dict(panel.frames)
    res = screen(bars, _kinds(bars), anchors=["ANCH1", "ANCH2"])
    assert res[0].symbol == "DEP1", f"expected DEP1 first, got {res[0].symbol}"
    assert res[0].scores["linkage"] > 5


def test_short_history_is_rejected_not_scored(panel):
    short = panel.frames["IND0"].iloc[:120]
    r = score_asset(short, "THIN", "equity")
    assert not r.usable and r.total == 0.0
    assert str(MIN_BARS) in r.reject_reason


def test_a_flat_price_is_rejected(panel):
    """Untradeable or stale: a data problem, not a low score."""
    dead = panel.frames["IND1"].copy()
    for c in ("open", "high", "low", "close"):
        dead[c] = 100.0
    dead["volume"] = 1.0
    r = score_asset(dead, "FLAT", "equity")
    assert not r.usable and "barely moves" in r.reject_reason


def test_an_asset_that_changed_scores_low_on_stability(panel):
    bars = panel.frames["IND2"].copy()
    half = len(bars) // 2
    # Second half is five times as volatile: a different asset, effectively.
    base = bars["close"].iloc[half]
    bars.iloc[half:, bars.columns.get_loc("close")] = (
        base * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.05, len(bars) - half))))
    for c in ("open", "high", "low"):
        bars[c] = bars["close"]
    r = score_asset(bars, "SHIFT", "equity")
    assert r.scores["stability"] < 5, "a regime change must show up as instability"


def test_selection_caps_one_asset_class(panel):
    bars = dict(panel.frames)
    res = screen(bars, _kinds(bars))
    picked = select(res, target=10, max_share=0.5)
    counts: dict[str, int] = {}
    for p in picked:
        counts[p.kind] = counts.get(p.kind, 0) + 1
    assert max(counts.values()) <= 5, f"one class dominated: {counts}"


def test_selection_never_takes_a_reject(panel):
    bars = dict(panel.frames)
    bars["THIN"] = panel.frames["IND0"].iloc[:80]
    k = _kinds(bars)
    k["THIN"] = "equity"
    picked = select(screen(bars, k), target=50)
    assert "THIN" not in {p.symbol for p in picked}


def test_explain_states_it_is_not_a_forecast(panel):
    bars = dict(panel.frames)
    text = explain(screen(bars, _kinds(bars)), target=5)
    assert "not a forecast of profit" in text
    assert "worth spending checks on" in text


def test_rotation_replaces_one_or_two_not_a_batch():
    assert RULES.max_drops_per_cycle <= 2, (
        "swapping many at once means the record you quote belongs to a different "
        "board than the one that earned it")


# ---------------------------------------------------------------- charts

@pytest.mark.parametrize("symbol,kind,expected", [
    ("NVDA", "equity", "NVDA"),
    ("SPY", "fund", "SPY"),
    ("RELIANCE.NS", "equity", "NSE:RELIANCE"),
    ("TCS.NS", "equity", "NSE:TCS"),
    ("BTC-USD", "crypto", "BINANCE:BTCUSDT"),
    ("SOL-USD", "crypto", "BINANCE:SOLUSDT"),
])
def test_symbol_mapping(symbol, kind, expected):
    assert tv_symbol(symbol, kind) == expected


def test_us_tickers_keep_no_guessed_prefix():
    """A wrong exchange prefix produces a blank chart, which is worse than none."""
    for sym in ("AAPL", "JPM", "QQQ", "XLF"):
        assert ":" not in tv_symbol(sym, "equity")


def test_chart_url_is_well_formed():
    url = chart_url("RELIANCE.NS", "equity")
    assert url.startswith("https://www.tradingview.com/chart/")
    assert "symbol=NSE:RELIANCE" in url and "interval=D" in url


def test_indicators_are_the_ones_the_models_use():
    note = indicator_note()
    for term in ("EMA", "RSI 14", "MACD", "Bollinger", "ATR 14", "Volume"):
        assert term in note
    assert len(STUDIES) >= 6


def test_charts_page_builds_and_links_out(tmp_path):
    assets = [{"symbol": "NVDA", "kind": "equity", "colour": "#00e676",
               "description": "Chips."},
              {"symbol": "BTC-USD", "kind": "crypto", "colour": "#ffd93d",
               "description": "Crypto."}]
    out = write_charts_page(assets, tmp_path / "c.html")
    text = out.read_text()
    assert "BINANCE:BTCUSDT" in text and "NVDA" in text
    assert "TradingView.widget" in text
    assert "Open" in text, "there must be a working link for when scripts do not run"


def test_report_never_embeds_a_widget(tmp_path):
    """The report's no-JavaScript guarantee is what makes it open on an iPhone.

    Built in memory rather than read from disk: the shipped file depends on
    whichever demo data was last generated, and a test that reads it is really
    testing that artefact.
    """
    from sigbot.export_app import build_export
    from sigbot.report import build_report

    h = build_report(build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                                  str(tmp_path / "w.db")))
    assert "<script" not in h.lower()
    assert "tv.js" not in h and "TradingView.widget" not in h


def test_assets_without_a_drawn_chart_fall_back_to_a_link(tmp_path):
    from sigbot.export_app import build_export
    from sigbot.report import build_report

    data = build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"))
    data["charts"] = []                     # nothing drawn
    h = build_report(data)
    assert "tradingview.com/chart" in h, "with no drawn chart there must be a link out"


def test_a_drawn_chart_replaces_the_link(tmp_path):
    from sigbot.export_app import build_charts, build_export
    from sigbot.providers.market import SyntheticProvider
    from sigbot.report import build_report

    data = build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"))
    first = data["board"]["assets"][0]["symbol"]
    prov = SyntheticProvider(seed=4)
    data["charts"] = build_charts({first: prov.history(first, "2024-01-01", "2026-08-01")},
                                  {first: "equity"})
    h = build_report(data)
    anchor = "#c-" + first.replace(".", "_").replace("-", "_")
    assert f'href="{anchor}"' in h, "a drawn chart should link to its own page"
    assert "<svg" in h and "<script" not in h.lower()
