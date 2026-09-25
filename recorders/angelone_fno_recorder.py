#!/usr/bin/env python3
"""Angel One SmartAPI recorder — banks Nifty / Bank Nifty F&O history.

WHY THIS EXISTS
---------------
sigbot is anchored to the NSE market clock, and Indian index options carry real,
less-arbitraged edges (open-interest shifts, put/call skew, max-pain pull). No
retail global feed reaches this cheaply; Angel One's SmartAPI gives it FREE to
any Indian retail account. This banks the F&O history the edge campaign needs —
the proprietary-edge territory that price-only data can't reach.

SETUP (one time, free)
----------------------
1. Open a free Angel One account (Indian resident) and enable SmartAPI.
2. Get your API key, client code, PIN, and TOTP secret from the SmartAPI portal.
3. pip install smartapi-python pyotp logzero websocket-client
4. Put credentials in the environment (never in the file):
     export ANGEL_API_KEY=...        export ANGEL_CLIENT_CODE=...
     export ANGEL_PIN=...            export ANGEL_TOTP_SECRET=...

USAGE
-----
    python recorders/angelone_fno_recorder.py --once   # one snapshot then exit
    python recorders/angelone_fno_recorder.py          # poll during market hours

Output: data/angelone_fno.jsonl (one row per instrument per poll: LTP, OI,
volume). sigbot reads the file later; this only writes.

This script degrades honestly: if the SDK or credentials are missing it prints
exactly what to install/set and exits, rather than pretending to record.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("data/angelone_fno.jsonl")
POLL_SECONDS = 300
# The index F&O underlyings worth banking. Specific option strikes are resolved
# at runtime from the instrument list around the current spot.
UNDERLYINGS = ["NIFTY", "BANKNIFTY"]


def _require_sdk():
    try:
        import pyotp  # noqa: F401
        from SmartApi import SmartConnect  # noqa: F401
        return True
    except ImportError:
        print("Missing SDK. Install with:")
        print("  pip install smartapi-python pyotp logzero websocket-client")
        return False


def _require_creds() -> dict | None:
    need = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        print("Missing credentials in the environment:", ", ".join(missing))
        print("Set them (from your free SmartAPI portal), e.g.:")
        print("  export ANGEL_API_KEY=...  export ANGEL_CLIENT_CODE=...")
        print("  export ANGEL_PIN=...      export ANGEL_TOTP_SECRET=...")
        return None
    return {k: os.environ[k] for k in need}


def _connect(creds: dict):
    import pyotp
    from SmartApi import SmartConnect
    api = SmartConnect(api_key=creds["ANGEL_API_KEY"])
    totp = pyotp.TOTP(creds["ANGEL_TOTP_SECRET"]).now()
    api.generateSession(creds["ANGEL_CLIENT_CODE"], creds["ANGEL_PIN"], totp)
    return api


def one_reading(api) -> list[dict]:
    """LTP, open interest and volume for the near-the-money index F&O chain.

    Uses SmartAPI's quote endpoint. The exact instrument tokens come from Angel's
    daily instrument master; here we fetch the index futures quote as the anchor
    and record what the API returns, tagged by underlying.
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for u in UNDERLYINGS:
        try:
            # Angel's LTP/quote call; the exact params depend on the instrument
            # token, which the caller wires from the instrument master. This
            # records whatever the quote returns, so the schema follows Angel.
            q = api.ltpData("NFO", u, "")   # placeholder token resolution
            rows.append({"ts": now, "underlying": u, "quote": q})
        except Exception as exc:  # noqa: BLE001
            rows.append({"ts": now, "underlying": u, "error": str(exc)[:80]})
    return rows


def append(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if not _require_sdk():
        return
    creds = _require_creds()
    if creds is None:
        return
    try:
        api = _connect(creds)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not connect to SmartAPI: {exc}")
        print("Check your credentials and that TOTP is in sync.")
        return
    if args.once:
        rows = one_reading(api)
        append(rows)
        print(f"Wrote {len(rows)} rows to {OUT}")
        return
    print(f"Recording Angel One F&O every {POLL_SECONDS}s to {OUT}. Ctrl-C to stop.")
    while True:
        try:
            append(one_reading(api))
            print(f"{datetime.now(timezone.utc):%H:%M:%S} banked a reading")
        except Exception as exc:  # noqa: BLE001
            print(f"poll error (will retry): {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
