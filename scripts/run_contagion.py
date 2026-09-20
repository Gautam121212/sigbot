#!/usr/bin/env python3
"""Build and evaluate the contagion network (Model C).

    python scripts/run_contagion.py --provider synthetic   # null + power control
    python scripts/run_contagion.py --provider yahoo       # real data

The synthetic run plants two known lag-1 relationships inside 58 unrelated
series. A correct screener finds exactly those two and nothing else. Run it
after any change to the screening or event-study code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigbot.config import CONTAGION_CANDIDATES, SETTINGS, UNIVERSE  # noqa: E402
from sigbot.contagion import (  # noqa: E402
    ContagionGates, build_network, event_response, gate,
)
from sigbot.providers.market import SyntheticNetworkProvider, YahooProvider  # noqa: E402


def _tomorrow() -> str:
    """A fixed end date goes stale and makes every download fail."""
    return (datetime.now(timezone.utc)
            + timedelta(days=1)).strftime("%Y-%m-%d")


# If the first several symbols fail, the rest will too. Reporting that after
# six is more useful than reporting it after a hundred and twenty-seven.
STOP_AFTER = 6


def load_real(symbols: list[str], start: str, end: str, interval: str = "1d") -> dict[str, pd.Series]:
    market = YahooProvider()
    out: dict[str, pd.Series] = {}
    failures = 0
    for s in symbols:
        try:
            df = market.history(s, start, end, interval)
            out[s] = np.log(df["close"]).diff().dropna()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  skip {s}: {type(exc).__name__}")
            if failures >= STOP_AFTER and not out:
                raise SystemExit(
                    f"\n{failures} symbols in a row failed and none succeeded.\n"
                    f"The last was {s}: {type(exc).__name__}: {exc}\n\n"
                    "This is a problem with the request, not the market. "
                    "For a 15m screen Yahoo keeps only the last 60 days, "
                    "so pick a start date well inside that window."
                ) from exc
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["synthetic", "yahoo"], default="synthetic")
    ap.add_argument("--start", default=SETTINGS.history_start)
    ap.add_argument("--end", default=_tomorrow())
    ap.add_argument("--interval", default="1d",
                    choices=["1d", "1h", "15m", "5m"],
                    help="bar size. Yahoo keeps roughly 60 days of 15m history, "
                         "so an intraday screen can only ever be validated "
                         "forward, never backfilled")
    ap.add_argument("--alpha", type=float, default=0.10, help="target FDR")
    ap.add_argument("--sigma", type=float, default=2.0, help="anchor shock threshold")
    args = ap.parse_args()

    if args.provider == "synthetic":
        anchors = [f"A{i}" for i in range(10)]
        planted = {"D": ("A0", 0.35), "E": ("A1", 0.20)}
        prov = SyntheticNetworkProvider(anchors=anchors, couplings=planted,
                                        independents=[f"N{i}" for i in range(48)],
                                        n_days=3000, seed=5)
        returns = prov.log_returns()
        candidates = ["D", "E"] + [f"N{i}" for i in range(48)]
        print(f"CONTROL RUN — 2 planted links hidden among {len(candidates)} candidates\n")
    else:
        anchors = [a.symbol for a in UNIVERSE]
        candidates = CONTAGION_CANDIDATES
        print(f"Loading {len(anchors)} anchors and {len(candidates)} candidates...")
        returns = load_real(sorted(set(anchors + candidates)), args.start, args.end, args.interval)
        anchors = [a for a in anchors if a in returns]
        candidates = [c for c in candidates if c in returns]
        print()

    links = build_network(returns, anchors, candidates, alpha=args.alpha)
    survivors = sorted((lk for lk in links if lk.tradeable), key=lambda lk: lk.q_lagged)
    naive = sum(1 for lk in links if lk.p_lagged < 0.05)

    print("=" * 74)
    print(f"SCREEN: {len(links)} pairs tested, target FDR {args.alpha:.0%}")
    print(f"  uncorrected p<0.05 would report   {naive}")
    print(f"  surviving Benjamini-Hochberg      {len(survivors)}")
    print("=" * 74)

    if not survivors:
        print("\nNo lagged relationship survived correction.")
        print("On liquid large caps this is the expected result: information "
              "reaches dependents the same day, so there is nothing left to act on.")
        print("Same-day betas are large; that is not tradeable.")
        top = sorted(links, key=lambda lk: -abs(lk.beta_contemp))[:5]
        print("\nLargest SAME-DAY (untradeable) relationships, for context:")
        for lk in top:
            print("  ", lk.describe())
        return 0

    gates = ContagionGates()
    alertable = 0
    print()
    for lk in survivors[:25]:
        print(lk.describe())
        resp = event_response(returns[lk.anchor], returns[lk.dependent],
                              lk.anchor, lk.dependent, sigma=args.sigma)
        if resp is None:
            print("    event study: insufficient history\n")
            continue
        ok, blocked = gate(resp, lk, gates)
        print(f"    {resp.describe()}")
        if ok:
            alertable += 1
            print("    -> would alert\n")
        else:
            print(f"    -> blocked: {'; '.join(blocked)}\n")

    print("=" * 74)
    print(f"{alertable} of {len(survivors)} surviving links pass the alert gates.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
