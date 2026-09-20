"""Feature engineering.

INVARIANT: every column at index t may only use bars with index <= t.
`tests/test_leakage.py` enforces this by truncation-equivalence, not by
reading the code. If you add a feature, the test will catch a lookahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "ret_1", "ret_5", "ret_20",
    "vol_20", "vol_ratio",
    "rsi_14",
    "dist_sma20", "dist_sma50", "dist_sma200",
    "macd_hist_n",
    "atr_pct",
    "vol_z_20",
    "range_pct",
    "gap_pct",
    "hi252_dist", "lo252_dist",
]


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV -> feature frame. Index preserved. No forward information used."""
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {sorted(missing)}")

    c = df["close"].astype(float)
    out = pd.DataFrame(index=df.index)

    logc = np.log(c)
    out["ret_1"] = logc.diff(1)
    out["ret_5"] = logc.diff(5)
    out["ret_20"] = logc.diff(20)

    r1 = out["ret_1"]
    out["vol_20"] = r1.rolling(20).std()
    out["vol_ratio"] = r1.rolling(5).std() / out["vol_20"].replace(0.0, np.nan)

    out["rsi_14"] = _rsi(c, 14)

    for w in (20, 50, 200):
        sma = c.rolling(w).mean()
        out[f"dist_sma{w}"] = c / sma - 1.0

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    out["macd_hist_n"] = (macd - macd.ewm(span=9, adjust=False).mean()) / c

    out["atr_pct"] = _atr(df, 14) / c

    v = df["volume"].astype(float)
    vmean, vstd = v.rolling(20).mean(), v.rolling(20).std()
    out["vol_z_20"] = (v - vmean) / vstd.replace(0.0, np.nan)

    out["range_pct"] = (df["high"] - df["low"]) / c
    out["gap_pct"] = df["open"] / c.shift(1) - 1.0

    out["hi252_dist"] = c / c.rolling(252).max() - 1.0
    out["lo252_dist"] = c / c.rolling(252).min() - 1.0

    return out[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)


def build_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Next-day outcome. Row t holds the return realised between t and t+1.

    The last row is NaN by construction. Any model that trains on it is
    training on the future.
    """
    c = df["close"].astype(float)
    fwd = c.shift(-1) / c - 1.0
    return pd.DataFrame({"fwd_ret": fwd, "y_up": (fwd > 0).astype(float).where(fwd.notna())},
                        index=df.index)


def build_dataset(df: pd.DataFrame) -> pd.DataFrame:
    x = build_features(df)
    y = build_labels(df)
    return pd.concat([x, y], axis=1)
