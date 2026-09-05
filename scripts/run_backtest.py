#!/usr/bin/env python3
"""Walk-forward backtest over the universe.

    python scripts/run_backtest.py --provider synthetic     # null test, offline
    python scripts/run_backtest.py --provider yahoo         # real data

The synthetic run is not a formality. It is the control experiment: the data
contains no predictable structure, so any reported edge is a bug. Run it after
every change to the feature or model code.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigbot.backtest import walk_forward  # noqa: E402
from sigbot.config import SETTINGS, UNIVERSE  # noqa: E402
from sigbot.features import build_dataset  # noqa: E402
from sigbot.providers.market import SyntheticProvider, YahooProvider  # noqa: E402
from sigbot.stats import wilson_interval  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["synthetic", "yahoo"], default="synthetic")
    ap.add_argument("--start", default=SETTINGS.history_start)
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--out", default="backtest_predictions.csv")
    args = ap.parse_args()

    market = SyntheticProvider() if args.provider == "synthetic" else YahooProvider()
    assets = [a for a in UNIVERSE if not args.symbols or a.symbol in args.symbols]

    results, frames = [], []
    for asset in assets:
        try:
            df = market.history(asset.symbol, args.start, args.end)
            res = walk_forward(build_dataset(df), symbol=asset.symbol,
                               train_window=SETTINGS.train_window,
                               step=SETTINGS.refit_step,
                               gates=SETTINGS.gates_for(asset))
        except Exception as exc:  # noqa: BLE001
            print(f"{asset.symbol}: FAILED — {type(exc).__name__}: {exc}")
            continue
        if res.n_predictions == 0:
            print(f"{asset.symbol}: insufficient history")
            continue
        print(res.summary(), "\n")
        results.append(res)
        if not res.predictions.empty:
            f = res.predictions.copy()
            f["symbol"] = asset.symbol
            frames.append(f)

    if not results:
        print("no results")
        return 1

    all_pred = pd.concat(frames)
    all_pred.to_csv(args.out)

    sig = all_pred[all_pred["side"] != "HOLD"]
    n_sig = len(sig)
    skill = np.mean([r.brier_baseline - r.brier for r in results])

    print("=" * 62)
    print(f"PORTFOLIO — {args.provider} data, {len(results)} symbols")
    print(f"  predictions              {len(all_pred)}")
    print(f"  mean Brier skill         {skill:+.5f}   (0 = no better than the base rate)")
    print(f"  mean ECE                 {np.mean([r.ece for r in results]):.4f}")
    print(f"  signals fired            {n_sig}  ({n_sig / max(len(all_pred),1):.2%} of days)")
    if n_sig:
        wins = float((sig['net'] > 0).sum())
        lo, hi = wilson_interval(wins, n_sig, 0.95)
        print(f"  signal hit rate          {wins / n_sig:.3f}  95% CI [{lo:.3f}, {hi:.3f}]")
        print(f"  mean net return/signal   {sig['net'].mean():+.4%}")
        print(f"  t-stat on net returns    {sig['net'].mean() / (sig['net'].std(ddof=1) / np.sqrt(n_sig)):.2f}")
    print(f"  predictions written to   {args.out}")
    print("=" * 62)
    if args.provider == "synthetic" and n_sig and skill > 0.005:
        print("WARNING: measurable skill on random data. There is a leak. Do not ship.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
