#!/usr/bin/env python3
"""Fetch YEARS of free crypto history via yfinance — the data sigbot lacked.

yfinance gives full daily history (BTC to 2014) with no key/limit/365-cap.

SETUP:  pip install yfinance pandas
USAGE:  python recorders/fetch_crypto_history.py
Output: data/crypto_history/<COIN>.csv and data/crypto_history/combined.jsonl
"""
from __future__ import annotations

import json
from pathlib import Path

COINS = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
         "ADA-USD", "AVAX-USD", "DOGE-USD", "LTC-USD", "LINK-USD"]
OUT = Path("data/crypto_history")


def _num(v) -> float:
    """Coerce a cell that pandas may hand back as a scalar or 1-element Series."""
    try:
        import pandas as pd
        if isinstance(v, pd.Series):
            v = v.iloc[0]
    except Exception:  # noqa: BLE001
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def fetch() -> int:
    try:
        import yfinance as yf
    except ImportError:
        print("Install first: pip install yfinance pandas")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    combined = []
    for coin in COINS:
        try:
            df = yf.download(coin, period="max", interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or df.empty:
                print(f"  {coin}: no data")
                continue
            # Newer yfinance returns MultiIndex columns (('Close','BTC-USD')).
            # Flatten to the first level so ["Close"] works.
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)
            df.to_csv(OUT / f"{coin}.csv")
            for date, row in df.iterrows():
                c = _num(row["Close"])
                v = _num(row["Volume"])
                if c != c:  # NaN guard
                    continue
                combined.append({
                    "coin": coin, "date": str(date)[:10],
                    "close": c, "volume": v,
                    "high": _num(row["High"]), "low": _num(row["Low"])})
            total += len(df)
            print(f"  {coin}: {len(df)} days ({str(df.index[0])[:10]} to today)")
        except Exception as exc:  # noqa: BLE001
            print(f"  {coin}: failed — {exc}")
    (OUT / "combined.jsonl").write_text(
        "\n".join(json.dumps(r) for r in combined) + "\n")
    print(f"\nFetched {total} coin-days across {len(COINS)} coins to {OUT}/")
    return total


if __name__ == "__main__":
    fetch()
