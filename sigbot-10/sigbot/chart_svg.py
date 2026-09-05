"""Charts drawn as SVG, with a plain-English reading underneath.

## Why not the TradingView widget

You were right that linking out is worse. Tapping a name should show the chart,
with the indicators already on it, not send you somewhere to add them yourself.

The obstacle was that the widget is JavaScript and the report has none, so that
it opens from Files on an iPhone. The answer is not to give up the guarantee —
it is to draw the chart here. SVG is markup. It renders in Quick Look, offline,
with scripts disabled, and it can carry exactly the indicators the models use
rather than whatever template you last had open.

## What is drawn

  price with EMA 20 / 50 / 200    the trend, and the distance from it
  Bollinger Bands                 the volatility envelope
  volume                          event days are detected from volume spikes
  RSI 14 in its own panel         momentum, with the 30 and 70 lines

## The reading

Under each chart is a sentence per indicator saying what it says *right now* —
"price is 4% above its 50-day average", "RSI at 71, stretched" — because an
indicator you cannot read is decoration. The reading describes the current
state. It does not forecast, and it says so.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

import numpy as np
import pandas as pd

W, H = 400, 190
RSI_H = 62
PAD_L, PAD_R, PAD_T, PAD_B = 6, 40, 8, 16
COL = {"price": "#e8e8f0", "ema20": "#00d4aa", "ema50": "#7c4dff",
       "ema200": "#ffd93d", "band": "#8b8b9a", "vol": "#2a2a38",
       "grid": "#1a1a24", "rsi": "#00d4aa", "up": "#00e676", "down": "#ff6b6b"}


@dataclass
class Reading:
    label: str
    value: str
    says: str


def _path(xs, ys) -> str:
    pts = [f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys) if np.isfinite(y)]
    return "M" + " L".join(pts) if pts else ""


def _scale(series: pd.Series, lo: float, hi: float, top: float, bot: float):
    rng = max(hi - lo, 1e-9)
    return bot - (series - lo) / rng * (bot - top)


def indicators(bars: pd.DataFrame) -> pd.DataFrame:
    c = bars["close"].astype(float)
    out = pd.DataFrame(index=bars.index)
    out["close"] = c
    for n in (20, 50, 200):
        out[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    sma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    out["bb_hi"] = sma20 + 2 * sd20
    out["bb_lo"] = sma20 - 2 * sd20
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["rsi"] = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(50)
    out["volume"] = bars["volume"].astype(float)
    return out


def read_chart(ind: pd.DataFrame) -> list[Reading]:
    """What each indicator says right now, in words rather than numbers alone."""
    last = ind.iloc[-1]
    c = float(last["close"])
    out: list[Reading] = []

    for n in (20, 50, 200):
        ema = float(last[f"ema{n}"])
        if not np.isfinite(ema) or ema == 0:
            continue
        gap = c / ema - 1
        out.append(Reading(
            f"{n}-day average", f"{gap:+.1%}",
            f"Price is {abs(gap):.1%} {'above' if gap > 0 else 'below'} its {n}-day "
            f"average. {'Above the 200-day is the usual definition of an uptrend.' if n == 200 else ''}".strip()))

    rsi = float(last["rsi"])
    if rsi >= 70:
        says = "Stretched after a run up. It can stay stretched for weeks."
    elif rsi <= 30:
        says = "Beaten down. Also not a reason to buy on its own."
    else:
        says = "Neither stretched nor beaten down."
    out.append(Reading("RSI (momentum)", f"{rsi:.0f}", says))

    hi, lo = float(last["bb_hi"]), float(last["bb_lo"])
    if np.isfinite(hi) and np.isfinite(lo) and hi > lo:
        pos = (c - lo) / (hi - lo)
        width = (hi - lo) / c
        out.append(Reading(
            "Volatility band", f"{width:.1%} wide",
            f"Price sits {pos:.0%} of the way up its normal range. "
            f"{'A narrow band often comes before a bigger move.' if width < 0.06 else 'A wide band means it has been moving a lot.'}"))

    vol = ind["volume"].tail(60)
    if len(vol) > 20 and vol.mean() > 0:
        z = (float(last["volume"]) - vol.mean()) / max(vol.std(), 1e-9)
        out.append(Reading(
            "Volume", f"{z:+.1f}x normal",
            "Unusually heavy — the kind of day the system treats as an event."
            if z > 2 else "Ordinary trading activity."))
    return out


def chart_svg(bars: pd.DataFrame, days: int = 180) -> str:
    """Price, moving averages, bands, volume and RSI. Pure markup, no scripts."""
    ind = indicators(bars).tail(days)
    if len(ind) < 20:
        return '<p class="note">Not enough history to draw a chart.</p>'

    n = len(ind)
    xs = np.linspace(PAD_L, W - PAD_R, n)
    top, bot = PAD_T, H - PAD_B
    lo = float(np.nanmin([ind["close"].min(), ind["bb_lo"].min()]))
    hi = float(np.nanmax([ind["close"].max(), ind["bb_hi"].max()]))
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = lo - pad, hi + pad

    def y(col):
        return _scale(ind[col], lo, hi, top, bot).to_numpy()

    vmax = float(ind["volume"].max()) or 1.0
    vh = 26
    bars_svg = "".join(
        f'<rect x="{x - 1:.1f}" y="{bot - v / vmax * vh:.1f}" width="2" '
        f'height="{v / vmax * vh:.1f}" fill="{COL["vol"]}"/>'
        for x, v in zip(xs, ind["volume"].to_numpy()))

    band = ""
    if np.isfinite(ind["bb_hi"]).any():
        up, dn = y("bb_hi"), y("bb_lo")
        ok = np.isfinite(up) & np.isfinite(dn)
        if ok.any():
            fwd = " ".join(f"{x:.1f},{v:.1f}" for x, v in zip(xs[ok], up[ok]))
            back = " ".join(f"{x:.1f},{v:.1f}" for x, v in zip(xs[ok][::-1], dn[ok][::-1]))
            band = f'<polygon points="{fwd} {back}" fill="{COL["band"]}" opacity="0.10"/>'

    # Averages first, price on top. Colour key is the column name, except the
    # price line, which is drawn from `close`.
    layers = [("ema200", "ema200", 1.1, 0.85), ("ema50", "ema50", 1.1, 0.85),
              ("ema20", "ema20", 1.1, 0.85), ("close", "price", 1.6, 1.0)]
    lines = "".join(
        f'<path d="{_path(xs, y(col))}" fill="none" stroke="{COL[colour]}" '
        f'stroke-width="{width}" opacity="{op}"/>'
        for col, colour, width, op in layers if col in ind.columns)

    last_c = float(ind["close"].iloc[-1])
    last_y = float(_scale(pd.Series([last_c]), lo, hi, top, bot).iloc[0])

    rt, rb = H + 6, H + RSI_H - 14
    ry = rb - ind["rsi"].to_numpy() / 100.0 * (rb - rt)
    rsi_svg = (
        f'<line x1="{PAD_L}" y1="{rb - 0.7 * (rb - rt):.1f}" x2="{W - PAD_R}" '
        f'y2="{rb - 0.7 * (rb - rt):.1f}" stroke="{COL["grid"]}" stroke-dasharray="2 3"/>'
        f'<line x1="{PAD_L}" y1="{rb - 0.3 * (rb - rt):.1f}" x2="{W - PAD_R}" '
        f'y2="{rb - 0.3 * (rb - rt):.1f}" stroke="{COL["grid"]}" stroke-dasharray="2 3"/>'
        f'<path d="{_path(xs, ry)}" fill="none" stroke="{COL["rsi"]}" stroke-width="1.2"/>'
        f'<text x="{W - PAD_R + 4}" y="{rt + 8}" fill="#8b8b9a" font-size="8">70</text>'
        f'<text x="{W - PAD_R + 4}" y="{rb:.0f}" fill="#8b8b9a" font-size="8">30</text>'
        f'<text x="{PAD_L}" y="{rt - 1}" fill="#8b8b9a" font-size="8">RSI 14</text>')

    return f'''<svg viewBox="0 0 {W} {H + RSI_H}" width="100%"
  xmlns="http://www.w3.org/2000/svg" role="img"
  aria-label="Price with moving averages, volume and RSI">
  <rect width="{W}" height="{H + RSI_H}" fill="none"/>
  {bars_svg}{band}{lines}
  <circle cx="{xs[-1]:.1f}" cy="{last_y:.1f}" r="2.5" fill="{COL['price']}"/>
  <text x="{xs[-1] + 5:.1f}" y="{last_y + 3:.1f}" fill="{COL['price']}"
    font-size="9" font-weight="700">{last_c:,.2f}</text>
  {rsi_svg}
</svg>'''


LEGEND = [("ema20", "20-day"), ("ema50", "50-day"), ("ema200", "200-day")]


def chart_block(bars: pd.DataFrame, symbol: str, description: str = "",
                days: int = 180) -> str:
    """Chart plus the reading, ready to drop into the report."""
    esc = html.escape
    try:
        svg = chart_svg(bars, days)
        readings = read_chart(indicators(bars))
    except Exception as exc:  # noqa: BLE001  # handled: returns a card saying the chart is unavailable
        return f'<div class="card"><p>Chart unavailable: {esc(type(exc).__name__)}</p></div>'

    legend = "".join(
        f'<span><i style="background:{COL[k]}"></i>{esc(lbl)}</span>' for k, lbl in LEGEND)
    rows = "".join(
        f"<dt>{esc(r.label)}</dt><dd>{esc(r.value)}</dd>" for r in readings)
    says = "".join(f"<li>{esc(r.says)}</li>" for r in readings if r.says)

    return f'''
  <div class="card">
    {f'<p class="what-sm">{esc(description)}</p>' if description else ''}
    {svg}
    <div class="legend chartkey">{legend}</div>
  </div>
  <h4>What the chart says right now</h4>
  <div class="card"><dl>{rows}</dl></div>
  <div class="card"><ul>{says}</ul>
    <p style="margin-top:10px">This describes where things stand today. None of it
    is a forecast — the models do not read charts, they count outcomes. Use this
    to see what the numbers on the other tabs are describing.</p></div>'''
