#!/usr/bin/env python3
"""Test funding ACCELERATION, not level — the second-derivative version.

The naive funding-level edge failed (flips between halves). But the edges that
work in this project are usually second-derivatives (rate of CHANGE, not level).
This tests whether funding RISING FAST (crowding building) predicts a drop, and
funding FALLING FAST predicts a bounce — a different signal from the level.

Reads the same local files. Run after pull_binance_prices.py.
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

FUNDING = Path("data/binance_funding_history.jsonl")
PRICES = Path("data/binance_prices.jsonl")


def _prices():
    out = defaultdict(dict)
    for ln in PRICES.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            out[r["symbol"]][date.fromisoformat(r["date"])] = r["close"]
    return out


def _daily_funding():
    tmp = defaultdict(lambda: defaultdict(list))
    for ln in FUNDING.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            tmp[r["symbol"]][datetime.fromisoformat(r["ts"]).date()].append(r["funding_rate"])
    return {s: {d: sum(v) / len(v) for d, v in days.items()} for s, days in tmp.items()}


def main() -> None:
    if not (FUNDING.exists() and PRICES.exists()):
        print("Need both data files. Run the backfill and pull_binance_prices.py.")
        return
    prices, funding = _prices(), _daily_funding()
    buckets = {"funding spiking UP (crowding fast)": {"h1": [], "h2": []},
               "funding dropping FAST (unwind)": {"h1": [], "h2": []},
               "funding stable": {"h1": [], "h2": []}}
    for sym in funding:
        if sym not in prices:
            continue
        days = sorted(set(funding[sym]) & set(prices[sym]))
        mid = len(days) // 2
        for i, day in enumerate(days):
            prev = day - timedelta(days=3)
            fwd = day + timedelta(days=3)
            if prev not in funding[sym] or fwd not in prices[sym]:
                continue
            # acceleration = change in funding over the last 3 days
            accel = (funding[sym][day] - funding[sym][prev]) * 100
            r = (prices[sym][fwd] / prices[sym][day] - 1) * 100
            half = "h1" if i < mid else "h2"
            key = ("funding spiking UP (crowding fast)" if accel > 0.01 else
                   "funding dropping FAST (unwind)" if accel < -0.01 else
                   "funding stable")
            buckets[key][half].append(r)
    print("\nFUNDING ACCELERATION EDGE — next-3-day return by funding CHANGE")
    print("=" * 64)
    print(f"{'bucket':<36}{'half1':>14}{'half2':>14}")
    for name, h in buckets.items():
        a1 = f"{st.mean(h['h1']):+.2f}%(n={len(h['h1'])})" if len(h['h1']) >= 15 else "thin"
        a2 = f"{st.mean(h['h2']):+.2f}%(n={len(h['h2'])})" if len(h['h2']) >= 15 else "thin"
        print(f"{name:<36}{a1:>14}{a2:>14}")
    print("\nEdge = a bucket consistently one direction in BOTH halves.")


if __name__ == "__main__":
    main()
