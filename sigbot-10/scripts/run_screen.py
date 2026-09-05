#!/usr/bin/env python3
"""Screen the candidate pool and set the board to the best 100.

    python scripts/run_screen.py --provider synthetic   # offline check
    python scripts/run_screen.py --provider yahoo       # real data

Selection is measured, not guessed: liquidity, whether daily moves clear costs,
whether behaviour held across both halves of history, reactivity to event days,
and whether it follows any anchor with a next-day lag that survives correction.
A high score says the asset is worth spending checks on — not that it will pay.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigbot.config import POOL, SETTINGS, UNIVERSE  # noqa: E402
from sigbot.providers.market import SyntheticNetworkProvider, YahooProvider  # noqa: E402
from sigbot.screener import explain, screen, select  # noqa: E402
from sigbot.watchlist import Watchlist  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["synthetic", "yahoo"], default="synthetic")
    ap.add_argument("--start", default=SETTINGS.history_start)
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--db", default="watchlist.db")
    ap.add_argument("--replace", action="store_true",
                    help="rebuild a board that is already full")
    ap.add_argument("--apply", action="store_true", help="write the board, not just report")
    args = ap.parse_args()

    if args.provider == "synthetic":
        prov = SyntheticNetworkProvider(
            anchors=[f"A{i}" for i in range(6)], couplings={"D1": ("A0", 0.4)},
            independents=[f"N{i}" for i in range(40)], n_days=1200, seed=5)
        bars = dict(prov.frames)
        kinds = {k: ("crypto" if k.startswith("N") else "equity") for k in bars}
        anchors = [f"A{i}" for i in range(6)]
        print(f"CONTROL RUN — {len(bars)} synthetic assets, one planted link\n")
    else:
        market = YahooProvider()
        end = "2030-01-01"
        bars, kinds = {}, {}
        print(f"Loading {len(POOL)} candidates...")
        for a in POOL:
            try:
                bars[a.symbol] = market.history(a.symbol, args.start, end)
                kinds[a.symbol] = a.kind
            except Exception as exc:  # noqa: BLE001
                print(f"  skip {a.symbol}: {type(exc).__name__}")
        anchors = [a.symbol for a in UNIVERSE if a.symbol in bars][:20]
        print()

    # Feed the live record in. Without this, `track_record` sits at its
    # neutral value forever and the criterion does nothing.
    records = {}
    try:
        from sigbot.runner import board_records

        records = board_records(SETTINGS)
        if records:
            thick = sum(1 for n, _ in records.values() if n >= 60)
            print(f"Live record: {len(records)} asset(s), {thick} with 60+ checks "
                  "(only those influence the screen).\n")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read the ledger ({type(exc).__name__}) — screening "
              "without the live record.\n")

    results = screen(bars, kinds, anchors=anchors, records=records)
    print(explain(results, args.target))

    if args.apply or args.replace:
        picked = select(results, args.target)
        wl = Watchlist(args.db)
        current = set(wl.symbols())
        wanted = {r.symbol for r in picked}
        joining, leaving = wanted - current, current - wanted

        if not current:
            chosen = [type("A", (), {"symbol": r.symbol, "kind": r.kind})()
                      for r in picked]
            added = wl.seed(chosen, args.target)
            print(f"\nBoard set: {added} added.")
        elif not joining and not leaving:
            print(f"\nThe screen agrees with the board — all {len(current)} "
                  "assets keep their slot.")
        elif not args.replace:
            # Saying "0 added" here reads like success while the screen result
            # is thrown away. It happened once before; it does not happen again.
            print(f"\nThe board already holds {len(current)} assets, so nothing "
                  "was written.")
            print(f"The screen would swap {len(leaving)} out and "
                  f"{len(joining)} in:")
            if joining:
                print(f"  in : {', '.join(sorted(joining)[:12])}")
            if leaving:
                print(f"  out: {', '.join(sorted(leaving)[:12])}")
            print("\nRe-run with --replace to act on it. Note that a replaced "
                  "asset loses its slot but keeps its ledger history — the "
                  "record is not deleted, only the attention.")
        else:
            for symbol in leaving:
                wl.drop(symbol, 0, None, None, "replaced by a re-screen")
            chosen = [type("A", (), {"symbol": r.symbol, "kind": r.kind})()
                      for r in picked]
            added = wl.seed(chosen, args.target)
            print(f"\nBoard rebuilt: {len(leaving)} out, {added} in, "
                  f"{len(wl.symbols())} on the board.")
    else:
        print("\nNothing written. Re-run with --apply to set the board.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
