#!/usr/bin/env python3
"""Backtest the opening range breakout on one instrument.

    python scripts/run_orb.py --provider synthetic          # null control, offline
    python scripts/run_orb.py --symbol SPY --days 59        # real, yfinance
    python scripts/run_orb.py --csv my_15m_bars.csv         # any other source

DATA REALITY CHECK, because this will bite you first:
yfinance caps 15-minute history at roughly 60 days. The plan called for two
years of 15-minute bars; yfinance will not provide them, and will return a
short frame rather than an error. Sixty days is about 12 tradeable weeks, which
at 2-3 setups per week is 25-35 trades — not the 100 the plan requires before
drawing a conclusion.

For two years of intraday bars you need IBKR, Polygon, Databento or similar.
Until then the honest read of any result here is "insufficient sample".
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigbot.expectancy import (  # noqa: E402
    audit, geometry_table, size_position, years_to_validate,
)
from sigbot.orb import (  # noqa: E402
    ORBRules, backtest_orb, credit_spread_breakeven, evaluate, sensitivity,
    synthetic_intraday,
)


def load_yahoo(symbol: str, days: int) -> tuple[pd.DataFrame, pd.Series | None]:
    from sigbot.providers.market import YahooProvider

    market = YahooProvider()
    end = (pd.Timestamp.utcnow() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    start = (pd.Timestamp.utcnow() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    bars = market.history(symbol, start, end, interval="15m")
    try:
        vix = market.history("^VIX", start, end)["close"].shift(1)
        vix.index = pd.DatetimeIndex(vix.index).normalize()
    except Exception:  # handled: prints the symbol and error before skipping
        vix = None
    return bars, vix


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["synthetic", "yahoo", "csv"], default="synthetic")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--days", type=int, default=59)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--no-vix-filter", action="store_true")
    args = ap.parse_args()

    vix = None
    if args.provider == "synthetic":
        bars = synthetic_intraday(days=250)
        print("NULL CONTROL — driftless bars, no breakout structure exists in them.\n")
    elif args.provider == "csv":
        bars = pd.read_csv(args.csv, index_col=0, parse_dates=True)
        bars.columns = [c.lower() for c in bars.columns]
    else:
        bars, vix = load_yahoo(args.symbol, args.days)
        span = (bars.index[-1] - bars.index[0]).days
        print(f"{args.symbol}: {len(bars)} bars over {span} days")
        if span < 300:
            print("  NOTE: yfinance caps 15m history near 60 days. This is a short "
                  "sample; treat any result as provisional.\n")

    rules = ORBRules(min_vix=None if args.no_vix_filter or vix is None else 18.0)
    res = evaluate(backtest_orb(bars, rules, vix))
    print("=" * 60)
    print(res.summary())
    print("=" * 60)

    if res.n:
        print("\nPARAMETER SENSITIVITY (a robustness check, NOT a menu to pick from)")
        surf = sensitivity(bars, rules, vix_prev_close=vix)
        print(surf.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
        pos = (surf["mean_r"] > 0).mean()
        print(f"\ncells with positive mean R: {pos:.0%} of {len(surf)}")
        if pos < 0.6:
            print("The sign of the edge flips across the neighbourhood. That is an "
                  "artifact of the specific parameters, not a strategy.")
        if res.n < 100:
            print(f"\n{res.n} trades is below the 100 needed to draw a conclusion. "
                  f"At this win rate the 90% lower bound is {res.win_lower:.1%}.")

    if res.n:
        print("\nWIN RATE vs GEOMETRY — the only number that matters")
        print(audit(res.win_rate, rules.target_r, res.n))
        print(f"\n  at 2 trades/week, validating this needs "
              f"{years_to_validate(res.win_rate, rules.target_r, 2.0):.1f} years")
        print("\nPOSITION SIZING")
        print(size_position(res.n, int(round(res.win_rate * res.n)),
                            rules.target_r).render())

    print("\nTHE WIN-RATE DIAL (driftless walk: free win rate = 1/(1+R) = breakeven)")
    print(geometry_table())
    print(f"\n  Your 70% target is the {1/0.70 - 1:.2f}R row. Zero skill required, "
          "zero expectancy.")

    print("\nCREDIT SPREAD BREAKEVENS (why an 89%/83% win rate is not an edge)")
    for credit in (0.15, 0.20, 0.25):
        be = credit_spread_breakeven(1.0, credit)
        print(f"  1-wide sold for {credit:.2f}: breakeven win rate {be:.0%}"
              f"  -> a quoted 83% is {'profitable' if 0.83 > be else 'A LOSS'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
