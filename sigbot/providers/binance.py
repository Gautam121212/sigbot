"""Binance klines — free, no key, and the only source here that gives minutes.

Yahoo keeps roughly 60 days of 15-minute history and throttles hard; CoinGecko
gives daily only. Binance gives 1m upward, a thousand bars a request, no key,
and rate limits generous enough that a hundred symbols every quarter hour is
nowhere near them.

## Why intraday crypto is the one thing that changes the arithmetic

The daily model records one checkable forecast per asset per day. A hundred
assets is a hundred observations a day, so a tier needing a hundred resolved
checks per asset takes months, and that is not a tuning problem — it is the
rate at which the market produces things to check.

Fifteen-minute bars on crypto produce ninety-six a day per asset. The same
hundred checks arrive in a day rather than a season.

## What that does not buy

Those observations are heavily correlated: ninety-six bars from one day of one
asset are not ninety-six independent facts, and on a day the whole market moves
together they are closer to one. `progress.py` already reports the day count
alongside the check count for exactly this reason, and it will matter far more
here than it does daily.

Worse, costs do not shrink with the horizon. A daily move of 1.5% clears a
0.1% round trip comfortably; a fifteen-minute move of 0.1% does not clear it at
all. So the gate has to be far stricter than the daily model's, or the ledger
fills with forecasts that were right and unprofitable.

Honest constraint: Binance is not available in every jurisdiction and its
public data endpoint is occasionally geo-blocked. This module does not work
around that — `scripts/check_sources.py` will show it failing, and the fallback
chain handles it as any other dead source.

Largest risk: that ninety-six checks a day feels like ninety-six times the
evidence. It is roughly one day's worth of information sampled more finely.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
BASE = "https://api.binance.com/api/v3/klines"
MAX_BARS = 1000                     # the endpoint's own ceiling

# Binance quotes against USDT, not USD. Treating the two as identical is a
# small lie that matters only in a crisis, when the peg is exactly what breaks.
QUOTE = "USDT"

INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d"}


class BinanceProvider:
    """OHLCV from Binance. Crypto only, by design."""

    name = "binance"

    def _symbol(self, symbol: str) -> str:
        if not symbol.endswith("-USD"):
            raise ValueError("Binance carries crypto only")
        return symbol.replace("-USD", "").upper() + QUOTE

    def history(self, symbol: str, start: str, end: str,
                interval: str = "15m") -> pd.DataFrame:
        bar = INTERVALS.get(interval)
        if bar is None:
            raise ValueError(f"unsupported interval {interval}")

        pair = self._symbol(symbol)
        start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

        rows: list[list] = []
        cursor = start_ms
        # Paginate rather than asking for everything: the endpoint caps each
        # response at a thousand bars and silently truncates rather than
        # erroring, which would look like a short history rather than a
        # partial fetch.
        while cursor < end_ms and len(rows) < 20 * MAX_BARS:
            url = (f"{BASE}?symbol={pair}&interval={bar}&startTime={cursor}"
                   f"&endTime={end_ms}&limit={MAX_BARS}")
            request = urllib.request.Request(url,
                                             headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
            if not batch:
                break
            rows.extend(batch)
            last_open = batch[-1][0]
            if last_open <= cursor:
                break                     # no progress; stop rather than loop
            cursor = last_open + 1

        if not rows:
            raise RuntimeError(f"Binance returned no bars for {pair}")

        frame = pd.DataFrame(rows, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_base",
            "taker_quote", "ignore"])
        frame.index = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        out = frame[["open", "high", "low", "close", "volume"]].dropna()
        # The final bar is still forming. Including it means predicting from a
        # candle that has not closed, which is a subtle way of using the future.
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        if len(out) and rows[-1][6] > now_ms:
            out = out.iloc[:-1]
        return out


def liquid_pairs(limit: int = 40) -> list[str]:
    """The most traded USDT pairs, as `TICKER-USD` symbols.

    Volume is the filter that matters at fifteen minutes: a thin pair's bars
    are mostly spread, and a model fitted to spread learns the spread.
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as resp:
        rows = json.loads(resp.read().decode("utf-8"))

    pairs = []
    for row in rows:
        pair = row.get("symbol", "")
        if not pair.endswith(QUOTE):
            continue
        base = pair[: -len(QUOTE)]
        # Leveraged tokens and stablecoin pairs are not assets with a view.
        if any(base.endswith(s) for s in ("UP", "DOWN", "BULL", "BEAR")):
            continue
        # A hardcoded list goes stale the moment someone launches another one:
        # USD1 and RLUSD both reached the ledger and produced fourteen and
        # thirteen misses each on moves of 0.1% and 0.0%. A pegged asset cannot
        # move, so every forecast on one is a coin flip on rounding error.
        if (base.startswith("USD") or base.endswith("USD")
                or base in ("USDC", "BUSD", "TUSD", "FDUSD", "DAI", "PYUSD",
                            "USDE", "USDS", "FRAX", "LUSD", "EURI", "AEUR",
                            "EUR", "GBP", "TRY", "BRL", "ARS", "JPY")):
            continue
        pairs.append((float(row.get("quoteVolume") or 0), f"{base}-USD"))

    pairs.sort(reverse=True)
    return [symbol for _volume, symbol in pairs[:limit]]
