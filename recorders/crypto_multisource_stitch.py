#!/usr/bin/env python3
"""Multi-source crypto history stitcher — the user's idea for building enough data.

The problem: no single crypto source gives a long BASIS history (perp vs spot
over time). The user's fix: pull different windows from different sources and
STITCH them until there's an adequate amount.

STRATEGY:
  - crypto.com candlesticks give perp price at multiple timeframes: 1D (long
    span, ~200 days), 4h and 1h (dense recent detail). Pull all three and merge.
  - CoinGecko gives spot price history (365 days daily).
  - Binance funding backfill (already built) gives a year of 8-hourly funding.
  - Join perp-close to spot-close per timestamp -> the BASIS time series.
  - Each source covers a different window/granularity; stitched, they span more
    than any one alone. Keep pulling windows until the merged series is long
    enough to backtest the structural edge (basis today -> return over N days).

This module MERGES readings the caller has fetched from each source (the MCP
fetches happen in the caller's client) into one basis time series, de-duplicating
by timestamp and preferring the denser source where they overlap. It reads and
writes data/crypto_basis_history.jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path("data/crypto_basis_history.jsonl")


def merge_basis(perp_bars: list[dict], spot_bars: list[dict],
                coin: str) -> list[dict]:
    """Join perp and spot closes by day into a basis series.

    perp_bars / spot_bars: [{"date": "YYYY-MM-DD", "close": float}, ...] from any
    source. Returns [{"date", "coin", "perp", "spot", "basis_pct"}].
    """
    spot_by_day = {b["date"]: b["close"] for b in spot_bars}
    out = []
    for b in perp_bars:
        d = b["date"]
        if d in spot_by_day and spot_by_day[d] > 0:
            basis = (b["close"] / spot_by_day[d] - 1) * 100
            out.append({"date": d, "coin": coin, "perp": b["close"],
                        "spot": spot_by_day[d], "basis_pct": round(basis, 4)})
    return out


def stitch_into_history(new_rows: list[dict]) -> int:
    """Merge new basis rows into the history file, de-duplicating by (coin, date).
    Returns the total row count after stitching."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                existing[(r["coin"], r["date"])] = r
    for r in new_rows:
        existing[(r["coin"], r["date"])] = r      # newer source wins on overlap
    rows = [existing[k] for k in sorted(existing)]
    OUT.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return len(rows)


def history_span() -> dict:
    """How much basis history is banked — so the caller knows when it's enough."""
    if not OUT.exists():
        return {"rows": 0, "coins": 0, "enough_to_test": False}
    rows = [json.loads(x) for x in OUT.read_text().splitlines() if x.strip()]
    coins = {r["coin"] for r in rows}
    per_coin = {}
    for r in rows:
        per_coin[r["coin"]] = per_coin.get(r["coin"], 0) + 1
    max_span = max(per_coin.values()) if per_coin else 0
    return {"rows": len(rows), "coins": len(coins),
            "max_days_one_coin": max_span,
            # need ~180 daily readings on several coins to test the edge
            "enough_to_test": max_span >= 180 and len(coins) >= 5}
