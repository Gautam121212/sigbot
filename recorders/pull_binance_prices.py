#!/usr/bin/env python3
"""Pull daily spot prices from Binance (same host as funding — no rate limit).

The funding-edge test hit CoinGecko's 429 rate limit. Binance's own klines
endpoint gives daily closes with no key and no limit, from the same host that
already worked for funding. This banks a year of daily prices so the funding
test (and every other crypto edge test) runs offline from one clean source.

USAGE:  python recorders/pull_binance_prices.py
Output: data/binance_prices.jsonl  (symbol, date, close)
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://fapi.binance.com"
OUT = Path("data/binance_prices.jsonl")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]


def klines(symbol: str, days: int = 400) -> list[dict]:
    url = f"{BASE}/fapi/v1/klines?symbol={symbol}&interval=1d&limit={days}"
    req = urllib.request.Request(url, headers={"User-Agent": "sigbot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = json.loads(r.read())
    out = []
    for k in raw:
        day = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date()
        out.append({"symbol": symbol, "date": day.isoformat(), "close": float(k[4])})
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with OUT.open("w", encoding="utf-8") as f:
        for sym in SYMBOLS:
            try:
                for row in klines(sym):
                    f.write(json.dumps(row) + "\n")
                    total += 1
                print(f"  {sym}: prices banked")
            except Exception as exc:  # noqa: BLE001
                print(f"  {sym}: failed — {exc}")
            time.sleep(0.3)
    print(f"Banked {total} daily prices to {OUT}.")


if __name__ == "__main__":
    main()
