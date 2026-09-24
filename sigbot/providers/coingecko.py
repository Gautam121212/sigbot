"""CoinGecko free public API — the crypto source after Binance was blocked.

WHY THIS REPLACES BINANCE
-------------------------
The crypto model ran on Binance 15-minute bars. Binance now returns 403
Forbidden to the GitHub runners (region block), so crypto stopped recording on
2026-09-07 and the model went silent. Binance is not coming back for this host.

CoinGecko's free public API needs no key, is not region-blocked, and gives
DAILY (and hourly) prices with volume. It does not give 15-minute bars — but
the 15-minute model never had an edge (11 direction tests failed), and the two
crypto edges that DO hold — the low-volume-drop rebound and leverage crowding —
are DAILY signals. So moving crypto to a daily CoinGecko horizon loses nothing
real and gains a source that actually works.

RATE LIMITS
-----------
The free tier allows roughly 10-30 calls a minute. One call lists the top
coins by volume; one call per coin fetches its daily history. Kept to ~40 coins
a run, well inside the limit, and each run is hours apart.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

BASE = "https://api.coingecko.com/api/v3"
TIMEOUT = 20.0
MAX_COINS = 40
HISTORY_DAYS = 90


def _get(path: str, opener=None):
    url = f"{BASE}{path}"
    if opener is not None:
        return json.loads(opener(url))
    req = urllib.request.Request(url, headers={"User-Agent": "sigbot/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def liquid_coins(limit: int = MAX_COINS, opener=None) -> list[str]:
    """Top coins by 24h volume — the liquid, tradeable set. Stablecoins dropped."""
    data = _get(f"/coins/markets?vs_currency=usd&order=volume_desc"
                f"&per_page={limit + 10}&page=1", opener)
    stable = {"tether", "usd-coin", "dai", "first-digital-usd", "true-usd",
              "binance-usd", "paxos-standard", "usdd"}
    out = []
    for c in data:
        cid = c.get("id", "")
        if cid and cid not in stable:
            out.append(cid)
        if len(out) >= limit:
            break
    return out


class CoinGeckoProvider:
    """Daily OHLC-ish history for a coin, as a DataFrame with close+volume."""

    def __init__(self, fetch=None):
        self._fetch = fetch

    def history(self, coin_id: str, days: int = HISTORY_DAYS) -> pd.DataFrame:
        """Daily open/high/low/close plus volume.

        OHLC comes from the ohlc endpoint (real highs and lows, which the
        forecast needs); volume comes from market_chart, merged by calendar
        day. If OHLC is unavailable, high/low fall back to the close so the
        forecast still runs on close-only data rather than crashing.
        """
        chart = _get(f"/coins/{coin_id}/market_chart?vs_currency=usd"
                     f"&days={days}&interval=daily", self._fetch)
        vol_by_day = {}
        for ts, v in chart.get("total_volumes", []):
            day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
            vol_by_day[day] = float(v)
        close_by_day = {}
        for ts, price in chart.get("prices", []):
            day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
            close_by_day[day] = float(price)

        ohlc_by_day = {}
        try:
            ohlc = _get(f"/coins/{coin_id}/ohlc?vs_currency=usd&days={days}",
                        self._fetch)
            for ts, o, h, low, c in ohlc:
                day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
                ohlc_by_day[day] = (float(o), float(h), float(low), float(c))
        except Exception:  # noqa: BLE001  # handled: fall back to close-only highs/lows
            ohlc_by_day = {}

        rows = []
        for day in sorted(close_by_day):
            c = close_by_day[day]
            o, h, low, _c = ohlc_by_day.get(day, (c, c, c, c))
            rows.append({"date": datetime(day.year, day.month, day.day,
                                          tzinfo=timezone.utc),
                         "open": o, "high": max(h, c), "low": min(low, c),
                         "close": c, "volume": vol_by_day.get(day, 0.0)})
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.set_index("date")
        return df
