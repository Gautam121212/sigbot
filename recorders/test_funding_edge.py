#!/usr/bin/env python3
"""Test the crypto funding-rate edge — reads LOCAL banked prices (no rate limit).

Reads data/binance_funding_history.jsonl + data/binance_prices.jsonl (both from
Binance, no CoinGecko, no 429). Measures whether extreme funding predicts the
next-3-day return, split into two halves for out-of-sample confirmation.

Run pull_binance_prices.py first, then this.
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

FUNDING = Path("data/binance_funding_history.jsonl")
PRICES = Path("data/binance_prices.jsonl")


def _load_prices() -> dict:
    out = defaultdict(dict)
    for line in PRICES.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["symbol"]][date.fromisoformat(r["date"])] = r["close"]
    return out


def _load_daily_funding() -> dict:
    tmp = defaultdict(lambda: defaultdict(list))
    for line in FUNDING.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            from datetime import datetime
            day = datetime.fromisoformat(r["ts"]).date()
            tmp[r["symbol"]][day].append(r["funding_rate"])
    return {s: {d: sum(v) / len(v) for d, v in days.items()}
            for s, days in tmp.items()}


def main() -> None:
    if not FUNDING.exists() or not PRICES.exists():
        print("Need both data/binance_funding_history.jsonl and "
              "data/binance_prices.jsonl. Run the backfill and pull_binance_prices.py.")
        return
    prices = _load_prices()
    funding = _load_daily_funding()
    buckets = {"very high (>0.03%)": {"h1": [], "h2": []},
               "high (0.015-0.03%)": {"h1": [], "h2": []},
               "mild pos (0-0.015%)": {"h1": [], "h2": []},
               "negative (<0)": {"h1": [], "h2": []}}
    for sym in funding:
        if sym not in prices:
            continue
        days = sorted(set(funding[sym]) & set(prices[sym]))
        mid = len(days) // 2
        for i, day in enumerate(days):
            fwd = day + timedelta(days=3)
            if fwd not in prices[sym]:
                continue
            f = funding[sym][day] * 100
            r = (prices[sym][fwd] / prices[sym][day] - 1) * 100
            half = "h1" if i < mid else "h2"
            key = ("very high (>0.03%)" if f > 0.03 else
                   "high (0.015-0.03%)" if f > 0.015 else
                   "negative (<0)" if f < 0 else "mild pos (0-0.015%)")
            buckets[key][half].append(r)
    print("\nFUNDING-RATE EDGE — next-3-day return by funding level")
    print("=" * 62)
    print(f"{'bucket':<24}{'half1':>18}{'half2':>18}")
    for name, h in buckets.items():
        a1 = f"{st.mean(h['h1']):+.2f}% (n={len(h['h1'])})" if len(h['h1']) >= 15 else "thin"
        a2 = f"{st.mean(h['h2']):+.2f}% (n={len(h['h2'])})" if len(h['h2']) >= 15 else "thin"
        print(f"{name:<24}{a1:>18}{a2:>18}")
    print("\nEdge = a bucket consistently one direction in BOTH halves.")


if __name__ == "__main__":
    main()
