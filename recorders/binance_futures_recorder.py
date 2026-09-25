#!/usr/bin/env python3
"""Binance crypto-futures recorder — banks funding rate + open interest history.

WHY THIS EXISTS
---------------
The single best untested crypto edge (from the 80-indicator research) is the
futures FUNDING RATE and OPEN INTEREST: when longs are crowded and paying to
stay long, a squeeze is more likely. sigbot could never test this because it
had no derivatives feed. Binance's PUBLIC futures REST endpoints give funding
and OI with NO key and NO account — reachable from India.

But a backtest needs HISTORY, and a live feed only gives now. So this script
runs on your Mac, polls every few minutes, and appends each reading to a local
JSONL file. Over days it banks the history the edge campaign will test on.

USAGE
-----
    python recorders/binance_futures_recorder.py           # runs forever, ~5-min polls
    python recorders/binance_futures_recorder.py --once     # a single reading, then exit

Output: data/binance_futures.jsonl (one JSON object per symbol per poll).
Leave it running (a terminal tab, or `nohup ... &`). sigbot reads the file
later; this script only writes.

If Binance's REST host is blocked from your network, the funding/OI endpoints
have a public mirror at fapi.binance.com — swap BASE below if needed.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://fapi.binance.com"          # Binance USD-M futures, public
OUT = Path("data/binance_futures.jsonl")
POLL_SECONDS = 300                          # 5 minutes
# The liquid pairs whose derivatives data is worth banking.
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
TIMEOUT = 15


def _get(path: str):
    req = urllib.request.Request(f"{BASE}{path}",
                                 headers={"User-Agent": "sigbot-recorder/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def one_reading() -> list[dict]:
    """Funding rate, mark price, and open interest for each symbol, right now."""
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    # premiumIndex gives mark price + last funding rate in one call for all symbols.
    try:
        prem = {d["symbol"]: d for d in _get("/fapi/v1/premiumIndex")}
    except Exception as exc:  # noqa: BLE001
        print(f"premiumIndex failed: {exc}")
        prem = {}
    for sym in SYMBOLS:
        row = {"ts": now, "symbol": sym}
        p = prem.get(sym)
        if p:
            row["mark_price"] = float(p.get("markPrice", 0) or 0)
            row["funding_rate"] = float(p.get("lastFundingRate", 0) or 0)
        try:
            oi = _get(f"/fapi/v1/openInterest?symbol={sym}")
            row["open_interest"] = float(oi.get("openInterest", 0) or 0)
        except Exception as exc:  # noqa: BLE001
            row["open_interest_error"] = str(exc)[:60]
        rows.append(row)
    return rows


def append(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one reading then exit")
    args = ap.parse_args()
    if args.once:
        rows = one_reading()
        append(rows)
        print(f"Wrote {len(rows)} rows to {OUT}")
        return
    print(f"Recording Binance futures every {POLL_SECONDS}s to {OUT}. Ctrl-C to stop.")
    while True:
        try:
            rows = one_reading()
            append(rows)
            got = sum(1 for r in rows if "funding_rate" in r)
            print(f"{datetime.now(timezone.utc):%H:%M:%S} banked {got}/{len(rows)} symbols")
        except Exception as exc:  # noqa: BLE001
            print(f"poll error (will retry): {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
