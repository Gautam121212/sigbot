#!/usr/bin/env python3
"""Test sigbot's OWN news-attention stream as a signal — genuinely unique.

WHY THIS IS SIGBOT-ONLY
-----------------------
Sigbot pulls GDELT global news and archives every story it scores, across its
whole universe, every run. The COUNT and TONE of what it processes per day is a
proprietary ATTENTION signal — a byproduct of sigbot running that no price-only
system produces. Big desks pay for attention/sentiment data; sigbot generates
its own for free as a side effect.

THE THESIS
----------
A surge in news volume/attention about the market precedes a volatility spike
and often a REVERSAL (peak attention = peak crowding = exhaustion). This tests
whether sigbot's own daily news count predicts the next few days' |move|.

Reads news_archive.jsonl (sigbot's archive) + data/binance_prices.jsonl (BTC as
the market proxy). Run pull_binance_prices.py first if needed.

Whatever it finds is RISKY by construction (a novel, unproven signal) — it goes
to the risky loop, not the trusted models, until it earns its place.
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ARCHIVE = Path("news_archive.jsonl")
PRICES = Path("data/binance_prices.jsonl")


def _news_per_day() -> dict:
    if not ARCHIVE.exists():
        return {}
    counts = defaultdict(int)
    for ln in ARCHIVE.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        ts = r.get("ts") or r.get("timestamp") or r.get("date") or ""
        d = str(ts)[:10]
        if len(d) == 10:
            counts[d] += 1
    return dict(counts)


def _btc_prices() -> dict:
    if not PRICES.exists():
        return {}
    out = {}
    for ln in PRICES.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r["symbol"] == "BTCUSDT":
                out[date.fromisoformat(r["date"])] = r["close"]
    return out


def main() -> None:
    news = _news_per_day()
    prices = _btc_prices()
    if not news:
        print("No news_archive.jsonl found — run sigbot so it archives news first.")
        return
    if not prices:
        print("No BTC prices — run pull_binance_prices.py first.")
        return
    counts = sorted(news.values())
    med = st.median(counts)
    print(f"news/day: median={med:.0f}, max={max(counts)} over {len(news)} days")

    # On high-attention days (2x median), what is BTC's next-3-day ABSOLUTE move
    # and signed move, vs normal days?
    hi_abs, hi_signed, norm_abs = [], [], []
    for dstr, count in news.items():
        try:
            d = date.fromisoformat(dstr)
        except ValueError:
            continue
        fwd = d + timedelta(days=3)
        if d not in prices or fwd not in prices:
            continue
        move = (prices[fwd] / prices[d] - 1) * 100
        if count > med * 2:
            hi_abs.append(abs(move)); hi_signed.append(move)
        else:
            norm_abs.append(abs(move))
    if len(hi_abs) >= 10 and len(norm_abs) >= 10:
        print(f"\nHigh-attention days (2x median news): {len(hi_abs)}")
        print(f"  next-3d |move|: {st.mean(hi_abs):.2f}%  (normal days: {st.mean(norm_abs):.2f}%)")
        print(f"  next-3d signed move: {st.mean(hi_signed):+.2f}%")
        if st.mean(hi_abs) > st.mean(norm_abs) * 1.2:
            print("  -> attention spikes DO precede bigger moves (volatility signal).")
        if st.mean(hi_signed) < -0.5:
            print("  -> and they lean NEGATIVE (peak attention = exhaustion/reversal).")
    else:
        print("\nNot enough overlapping days yet — needs more archived news.")


if __name__ == "__main__":
    main()
