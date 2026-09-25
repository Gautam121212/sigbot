#!/usr/bin/env python3
"""Binance funding-rate BACKFILL — pulls months of PAST funding history at once.

Unlike the live recorder (which banks from now forward), this hits Binance's
historical funding endpoint (/fapi/v1/fundingRate) and pulls the full past
funding-rate series per symbol. That means the crypto futures edge (crowded
leverage) can be TESTED IMMEDIATELY, not after weeks of live collection.

Funding is set every 8 hours, so a year is ~1,095 readings per symbol — plenty
to test an edge across regimes.

USAGE
-----
    python recorders/binance_funding_backfill.py            # ~1 year, all symbols
    python recorders/binance_funding_backfill.py --days 400

Output: data/binance_funding_history.jsonl (one row per symbol per 8h funding).
Reachable from India (the --once recorder already proved the host works).
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://fapi.binance.com"
OUT = Path("data/binance_funding_history.jsonl")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
TIMEOUT = 20
LIMIT = 1000                    # max rows per request


def _get(path: str):
    req = urllib.request.Request(f"{BASE}{path}",
                                 headers={"User-Agent": "sigbot-backfill/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def funding_for(symbol: str, start_ms: int) -> list[dict]:
    """All funding readings for a symbol since start_ms, paged."""
    rows, cursor = [], start_ms
    while True:
        batch = _get(f"/fapi/v1/fundingRate?symbol={symbol}"
                     f"&startTime={cursor}&limit={LIMIT}")
        if not batch:
            break
        for b in batch:
            rows.append({
                "ts": datetime.fromtimestamp(b["fundingTime"] / 1000,
                                             tz=timezone.utc).isoformat(),
                "symbol": symbol,
                "funding_rate": float(b["fundingRate"]),
            })
        if len(batch) < LIMIT:
            break
        cursor = batch[-1]["fundingTime"] + 1
        time.sleep(0.3)          # be gentle on the public endpoint
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    start_ms = int((datetime.now(timezone.utc)
                    - timedelta(days=args.days)).timestamp() * 1000)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with OUT.open("w", encoding="utf-8") as f:
        for sym in SYMBOLS:
            try:
                rows = funding_for(sym, start_ms)
                for r in rows:
                    f.write(json.dumps(r) + "\n")
                total += len(rows)
                print(f"  {sym}: {len(rows)} funding readings")
            except Exception as exc:  # noqa: BLE001
                print(f"  {sym}: failed — {exc}")
    print(f"Backfilled {total} funding readings to {OUT}.")
    print("The crypto futures edge can now be tested on this history.")


if __name__ == "__main__":
    main()
