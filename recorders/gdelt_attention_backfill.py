#!/usr/bin/env python3
"""GDELT attention backfill — pull HISTORICAL daily news volume, size-bounded.

Sigbot's own news archive only spans a couple of days (it rotates at 20k lines).
The attention edge needs months of daily volume. GDELT publishes historical
global article counts per day — the same source sigbot uses — so this pulls
that history at once and writes it to a TINY daily file (one row per day).

SIZE: one row per day = ~365 rows/year = a few KB. It can never bloat your Mac,
unlike the raw archive. This is the item-1 fix applied to the backfill too.

USAGE:  python recorders/gdelt_attention_backfill.py
        python recorders/gdelt_attention_backfill.py --query "bitcoin OR crypto"
Output: data/attention_daily.jsonl  (date, article_count, avg_tone)

Uses GDELT's DOC API timelinevol (volume) + timelinetone. If GDELT rate-limits
(429), it retries with backoff; GDELT is best-effort but this is a one-time pull.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path("data/attention_daily.jsonl")
API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _fetch(query: str, mode: str) -> dict:
    params = urllib.parse.urlencode({
        "query": query, "mode": mode, "format": "json", "timespan": "24m"})
    url = f"{API}?{params}"
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 sigbot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            if not body.strip():
                raise ValueError("empty response")
            return json.loads(body)
        except Exception as exc:  # noqa: BLE001
            wait = 15 * (attempt + 1)   # GDELT throttles hard; wait longer
            print(f"  GDELT busy ({str(exc)[:40]}), retrying in {wait}s...")
            time.sleep(wait)
    print("\nGDELT stayed rate-limited. This is common — it throttles far below")
    print("its documented cap. Two options:")
    print("  1. Wait 10-15 min and re-run (the limit resets).")
    print("  2. Skip the backfill: sigbot's own news_daily.jsonl accumulates one")
    print("     row/day as it runs, so the attention signal builds naturally.")
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="bitcoin OR cryptocurrency OR "
                    "\"stock market\" OR economy")
    args = ap.parse_args()
    print(f"Pulling GDELT daily volume for: {args.query}")
    vol = _fetch(args.query, "timelinevol")
    time.sleep(6)
    tone = _fetch(args.query, "timelinetone")

    # Merge the two series by date.
    counts: dict = {}
    for series in vol.get("timeline", []):
        for pt in series.get("data", []):
            day = str(pt.get("date", ""))[:10]
            if day:
                counts.setdefault(day, {})["volume"] = pt.get("value", 0)
    for series in tone.get("timeline", []):
        for pt in series.get("data", []):
            day = str(pt.get("date", ""))[:10]
            if day:
                counts.setdefault(day, {})["tone"] = pt.get("value", 0)

    if not counts:
        print("GDELT returned nothing (likely rate-limited). Try again shortly.")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"date": d, "volume": v.get("volume", 0), "tone": v.get("tone", 0)}
            for d, v in sorted(counts.items())]
    OUT.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    print(f"Banked {len(rows)} daily attention rows to {OUT} "
          f"(tiny — one row per day).")


if __name__ == "__main__":
    main()
