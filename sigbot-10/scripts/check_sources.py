#!/usr/bin/env python3
"""Which data sources actually answer from this machine.

Run it on the Mac and again on the server — the answers differ, because
datacenter addresses get blocked far more aggressively than home connections.
I could not test the fallbacks myself: this sandbox blocks every domain except
a small allowlist, so Stooq and CoinGecko returned 403 here regardless of
whether they work for you.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigbot.providers.fallback import (  # noqa: E402
    CoinGeckoProvider, StooqProvider, TwelveDataProvider,
)
from sigbot.providers.market import YahooProvider  # noqa: E402

START, END = "2026-06-01", "2026-08-31"
CASES = [("AAPL", "US equity"), ("RELIANCE.NS", "NSE equity"), ("BTC-USD", "crypto")]

print(f"Testing {START} to {END}, daily bars.\n")
grid: dict[str, dict[str, str]] = {}
for provider in (YahooProvider(), TwelveDataProvider(),
                 CoinGeckoProvider(), StooqProvider()):
    name = getattr(provider, "name", type(provider).__name__)
    grid[name] = {}
    for symbol, _kind in CASES:
        try:
            df = provider.history(symbol, START, END)
            grid[name][symbol] = f"{len(df)} bars" if len(df) else "empty"
        except Exception as exc:  # noqa: BLE001  # handled: the failure is the result — this script reports which sources answer, so an error is data
            grid[name][symbol] = f"{type(exc).__name__}"

width = max(len(n) for n in grid) + 2
print(" " * width + "".join(f"{s:<16}" for s, _ in CASES))
for name, results in grid.items():
    print(f"{name:<{width}}" + "".join(f"{results[s]:<16}" for s, _ in CASES))

covered = [s for s, _ in CASES
           if any("bars" in grid[n][s] for n in grid)]
print(f"\n{len(covered)} of {len(CASES)} asset types have at least one working "
      "source.")
if len(covered) < len(CASES):
    missing = [s for s, _ in CASES if s not in covered]
    print(f"No source for: {', '.join(missing)}. Those assets will be skipped "
          "and the skip recorded — they will not silently become 'no signal'.")
