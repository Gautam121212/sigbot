"""Market data providers.

Two implementations:
  YahooProvider     - real data via yfinance. Free, rate-limited, occasionally
                      wrong. Swap it for a paid feed before risking money.
  SyntheticProvider - geometric Brownian motion with no predictable structure.
                      Used by the null test: any pipeline that reports edge on
                      this data is broken, and that is the single most useful
                      thing you can learn before trusting a backtest.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd


class YahooProvider:
    name = "yahoo"

    def __init__(self, retries: int = 3, backoff: float = 2.0) -> None:
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError("pip install yfinance") from exc
        self.retries = retries
        self.backoff = backoff

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        """OHLCV at the requested interval, retrying on a rate limit.

        Yahoo throttles after a few hundred calls, which is why a symbol can
        succeed during the screen and fail during the daily run twenty minutes
        later. Without a retry that reads as "this asset has no data", which is
        a different and much more alarming conclusion than "wait a moment".

        Yahoo caps intraday history hard: roughly 60 days for 15m/5m bars and
        7 days for 1m. Anything asking for years of intraday data will silently
        come back short, so the caller must check what it actually received
        rather than assume the requested range.
        """
        import time

        import yfinance as yf

        raw = None
        for attempt in range(self.retries):
            raw = yf.download(symbol, start=start, end=end, interval=interval,
                              auto_adjust=True, progress=False, threads=False)
            if raw is not None and not raw.empty:
                break
            # Some failures are facts about the request, not bad luck. Waiting
            # two seconds does not bring 15m data from four months ago into
            # existence, and retrying it three times per symbol across a whole
            # universe costs a quarter of an hour to learn nothing.
            PERMANENT = ("must be within the last", "cannot be after",
                         "No timezone found", "possibly delisted")
            note = str(getattr(raw, "attrs", {}) or "") + str(symbol)
            if attempt < self.retries - 1 and not any(
                    p.lower() in note.lower() for p in PERMANENT):
                time.sleep(self.backoff * (attempt + 1))
            elif attempt < self.retries - 1:
                break
        if raw is None or raw.empty:
            raise RuntimeError(
                f"no data returned for {symbol} after {self.retries} attempts — "
                "either the ticker is wrong or Yahoo is rate limiting")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        idx = pd.to_datetime(df.index)
        df.index = idx.tz_localize(None) if idx.tz is None else idx.tz_convert("UTC").tz_localize(None)
        return df.dropna().sort_index()


class SyntheticProvider:
    name = "synthetic"

    """Reproducible random walk. No signal exists in it, by construction."""

    def __init__(self, seed: int = 7, annual_vol: float = 0.30, drift: float = 0.06):
        self.seed = seed
        self.annual_vol = annual_vol
        self.drift = drift

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        idx = pd.bdate_range(start=start, end=end)
        n = len(idx)
        # Built-in hash() is salted per process; use a stable digest so the
        # null control is byte-identical across runs and machines.
        digest = hashlib.sha256(f"{symbol}|{self.seed}".encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        sd = self.annual_vol / np.sqrt(252.0)
        r = rng.normal(self.drift / 252.0, sd, n)
        close = 100.0 * np.exp(np.cumsum(r))
        intraday = np.abs(rng.normal(0.0, sd, n))
        high = close * (1.0 + intraday)
        low = close * (1.0 - intraday)
        open_ = np.concatenate([[close[0]], close[:-1]]) * (1.0 + rng.normal(0, sd / 3, n))
        volume = rng.lognormal(15.0, 0.4, n)
        return pd.DataFrame(
            dict(open=open_, high=np.maximum.reduce([high, open_, close]),
                 low=np.minimum.reduce([low, open_, close]),
                 close=close, volume=volume),
            index=idx,
        )


class SyntheticNetworkProvider:
    """A panel of assets with a KNOWN dependency structure.

    Used for two tests that matter more than any backtest:
      null  — independent series must yield ~0 links after FDR control
      power — a planted lag-1 coupling must actually be detected

    A screener that fails either one is not measuring anything.
    """

    def __init__(self, anchors: list[str], couplings: dict[str, tuple[str, float]],
                 independents: list[str] | None = None, seed: int = 11,
                 annual_vol: float = 0.30, n_days: int = 3000,
                 start: str = "2013-01-01"):
        """couplings maps dependent -> (anchor, lag-1 beta)."""
        self.index = pd.bdate_range(start=start, periods=n_days)
        rng = np.random.default_rng(seed)
        sd = annual_vol / np.sqrt(252.0)

        rets: dict[str, np.ndarray] = {a: rng.normal(0, sd, n_days) for a in anchors}
        for name in independents or []:
            rets[name] = rng.normal(0, sd, n_days)
        for dep, (anchor, beta) in couplings.items():
            noise = rng.normal(0, sd, n_days)
            lagged = np.concatenate([[0.0], rets[anchor][:-1]])
            rets[dep] = beta * lagged + noise

        self.frames = {name: self._to_ohlcv(r, rng, sd) for name, r in rets.items()}

    def _to_ohlcv(self, r: np.ndarray, rng, sd: float) -> pd.DataFrame:
        close = 100.0 * np.exp(np.cumsum(r))
        intraday = np.abs(rng.normal(0.0, sd, r.size))
        open_ = np.concatenate([[close[0]], close[:-1]])
        return pd.DataFrame(
            dict(open=open_,
                 high=np.maximum.reduce([close * (1 + intraday), open_, close]),
                 low=np.minimum.reduce([close * (1 - intraday), open_, close]),
                 close=close,
                 volume=rng.lognormal(15.0, 0.4, r.size)),
            index=self.index,
        )

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        if symbol not in self.frames:
            raise RuntimeError(f"unknown symbol {symbol}")
        return self.frames[symbol].loc[start:end]

    def log_returns(self) -> dict[str, pd.Series]:
        return {k: np.log(v["close"]).diff().dropna() for k, v in self.frames.items()}
