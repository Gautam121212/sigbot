"""TradingView links and charts.

## Why this is links rather than embedded charts, in the main report

The report has no JavaScript on purpose: iOS previews HTML files with scripts
disabled, and a page that draws itself in script shows a title bar and nothing
else there. TradingView's chart widget is JavaScript. Embedding it would break
the one property that makes the report open on your phone at all.

So the report links out. On a phone a TradingView link opens the TradingView
app if it is installed, which gives you a better chart than any embed would.

`write_charts_page()` also produces a separate `charts.html` that *does* embed
live widgets with the indicators pre-loaded. It needs to be served over http or
https — GitHub Pages is fine — because scripts run there. Two files, each honest
about where it works, rather than one that half-works in both places.

## Indicators

These are the ones the models actually compute, not a decorative selection:

  EMA 20 / 50 / 200   trend, and the distance from them is a live feature
  RSI 14              momentum, used for the bucket boundaries
  MACD                trend changes
  Bollinger Bands     volatility range
  ATR 14              position sizing and the shock threshold
  Volume              event-day detection keys off volume spikes

The chart is for looking at what the numbers describe. Nothing in the models
reads a chart.
"""
from __future__ import annotations

import html
from pathlib import Path

# What the bot computes, in TradingView's own study identifiers.
STUDIES = [
    ("Moving Average Exponential", "EMA 20 / 50 / 200 — trend, and distance from it"),
    ("Relative Strength Index", "RSI 14 — momentum, sets the bucket boundaries"),
    ("MACD", "MACD — trend changes"),
    ("Bollinger Bands", "Bollinger Bands — volatility range"),
    ("Average True Range", "ATR 14 — sizing and the shock threshold"),
    ("Volume", "Volume — event days are detected from volume spikes"),
]
STUDY_IDS = ["STD;EMA", "STD;RSI", "STD;MACD", "STD;Bollinger_Bands", "STD;Average_True_Range"]

BASE = "https://www.tradingview.com/chart/"


def tv_symbol(symbol: str, kind: str = "equity") -> str:
    """Map a ledger symbol to TradingView's notation.

    Exchange prefixes are only applied where they are unambiguous. For US
    listings the bare ticker is left alone — TradingView resolves those itself,
    and a guessed prefix that is wrong produces a blank chart, which is worse
    than no prefix at all.
    """
    if symbol.endswith(".NS"):
        return f"NSE:{symbol[:-3]}"
    if symbol.endswith(".BO"):
        return f"BSE:{symbol[:-3]}"
    if symbol.endswith("-USD"):
        return f"BINANCE:{symbol[:-4]}USDT"
    if kind == "crypto":
        return f"BINANCE:{symbol}USDT"
    return symbol


def chart_url(symbol: str, kind: str = "equity", interval: str = "D") -> str:
    return f"{BASE}?symbol={tv_symbol(symbol, kind)}&interval={interval}"


def indicator_note() -> str:
    return ("Add these once in TradingView and save the layout — the link opens on "
            "whatever template you last used: "
            + "; ".join(label for _, label in STUDIES))


def write_charts_page(assets: list[dict], out: str | Path = "app/charts.html",
                      interval: str = "D") -> Path:
    """A live-chart page with the indicators pre-loaded.

    Requires serving over http/https. Opened straight from a file it will show
    the list and empty chart frames, because the widget needs scripts and a
    real origin. That is a property of the widget, not a bug here.
    """
    esc = html.escape
    rows = "".join(f"""
  <section class="chart">
    <header><span class="pip" style="background:{esc(a.get('colour', '#8b8b9a'))}"></span>
      <b>{esc(a['symbol'])}</b>
      <span class="tv">{esc(tv_symbol(a['symbol'], a.get('kind', 'equity')))}</span>
      <a class="out" href="{esc(chart_url(a['symbol'], a.get('kind', 'equity'), interval))}"
         target="_blank" rel="noopener">Open &rsaquo;</a></header>
    <p>{esc(a.get('description', ''))}</p>
    <div class="tvbox" data-symbol="{esc(tv_symbol(a['symbol'], a.get('kind', 'equity')))}"></div>
  </section>""" for a in assets)

    return _write(out, f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0a0a0f"><title>Charts</title>
<style>
:root{{--bg:#0a0a0f;--card:#111118;--line:#1a1a24;--teal:#00d4aa;--w:#fff;--g:#8b8b9a}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:Inter,-apple-system,sans-serif;background:var(--bg);color:var(--w);
padding:16px;max-width:430px;margin:0 auto}}
h1{{font-size:18px;font-weight:800;margin-bottom:6px}}
.note{{font-size:11.5px;color:var(--g);line-height:1.6;margin-bottom:18px}}
.chart{{background:var(--card);border:1.5px solid var(--line);border-radius:18px;
padding:14px;margin-bottom:12px}}
header{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
header b{{font-size:14px}}
.pip{{width:9px;height:9px;border-radius:50%}}
.tv{{font-size:10.5px;color:var(--g)}}
.out{{margin-left:auto;font-size:11.5px;color:var(--teal);font-weight:700;
text-decoration:none}}
.chart p{{font-size:11.5px;color:var(--g);line-height:1.45;margin-bottom:10px}}
.tvbox{{height:280px;border-radius:12px;overflow:hidden;background:#0d0d14}}
</style></head><body>
<h1>Charts</h1>
<p class="note">{esc(indicator_note())}<br><br>
Charts need this page served over http or https. Opened straight from a file the
frames stay empty — the widget cannot run without a real origin. The
<b>Open &rsaquo;</b> links work everywhere and launch the TradingView app on a
phone.</p>
{rows}
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
document.querySelectorAll('.tvbox').forEach(function (box, i) {{
  box.id = 'tv_' + i;
  try {{
    new TradingView.widget({{
      container_id: box.id, symbol: box.dataset.symbol, interval: '{interval}',
      theme: 'dark', style: '1', locale: 'en', autosize: true,
      hide_side_toolbar: true, allow_symbol_change: false,
      studies: {STUDY_IDS!r}
    }});
  }} catch (e) {{
    box.innerHTML = '<p style="padding:14px;font-size:12px;color:#8b8b9a">' +
      'Chart unavailable here. Use the Open link.</p>';
  }}
}});
</script></body></html>""")


def _write(out: str | Path, text: str) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
