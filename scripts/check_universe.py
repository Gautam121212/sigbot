#!/usr/bin/env python3
"""Whether the listing sources answer from this machine, and what they return.

I could not test these: the sandbox allows a short domain list and all three
returned 403 regardless of whether they work for you. NSE in particular is
known to refuse requests that do not look like a browser, and the header set
that works changes.

    python scripts/check_universe.py            probe each source
    python scripts/check_universe.py --write    save the pool to universe.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigbot.providers.scanner import build, describe  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("Fetching candidate lists (three requests, not one per symbol)...\n")
    universe = build()
    print(describe(universe))

    if not universe.candidates:
        print("\nNothing came back. The pool stays as it is — a screen with no "
              "candidates would replace your board with nothing.")
        return 1

    if "--write" in argv:
        path = ROOT / "universe.json"
        path.write_text(json.dumps(
            [{"symbol": c.symbol, "name": c.name, "kind": c.kind,
              "exchange": c.exchange, "market_cap": c.market_cap,
              "volume": c.volume} for c in universe.candidates], indent=1),
            encoding="utf-8")
        print(f"\nWrote {path}. The screen can read it with:")
        print("  python scripts/run_screen.py --provider yahoo --universe "
              "universe.json --apply")
        print("\nDownloading bars for every candidate is the expensive part — "
              f"roughly {len(universe.candidates) * 2 // 60} minutes at Yahoo's "
              "throttle. Run it overnight, not interactively.")
    else:
        print("\nRe-run with --write to save the pool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
