"""Fallback chain — when one data source fails, try the next.

A single provider is a single point of failure, and the way it fails matters:
Yahoo does not go down cleanly, it rate-limits, returns empty frames, or blocks
a datacenter address entirely. On the Mac that shows up as a bad afternoon. On
a server it can mean the system records "no data" for weeks while looking
perfectly healthy.

## What it does not fix

Falling back does not make the data equivalent. Stooq's daily bars are adjusted
differently from Yahoo's, and a price series stitched from two sources has a
seam at the switch — a return computed across it is partly an artifact of the
change. So the source is recorded on every fetch, and `stitched()` reports when
a symbol's history came from more than one place.

Honest constraint: only daily bars are portable across these sources. Stooq has
no intraday and CoinGecko no equities, so an intraday run still depends on
Yahoo alone. The chain reports that rather than silently returning daily bars
when 15m was asked for.

Largest risk: that a fallback quietly produces worse data that still looks like
data. Every provider is checked by `integrity.verify` before its result is
accepted, and a provider that returns something impossible is treated as having
failed rather than as having answered.

Test gap: the live sources are not called in tests. The chain logic is tested
with fakes; whether Stooq is up today is not something a test can settle.
"""
from __future__ import annotations

import io
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from ..integrity import verify
from ..skips import record_skip

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


class Provider(Protocol):
    name: str

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame: ...


@dataclass
class Attempt:
    provider: str
    ok: bool
    reason: str = ""
    rows: int = 0


class StooqProvider:
    """Daily bars from Stooq. Currently blocked — kept for the record.

    Stooq answers HTTP 200 with a three-line HTML interstitial rather than CSV
    when the request does not come from a browser. That is worse than a clean
    failure: at the HTTP level it looks like success, and only the header check
    below catches it.

    Left in the chain because it costs one failed attempt and might come back,
    but it is not counted as coverage. If you need a working equity fallback,
    that is TwelveDataProvider, which needs a free key.
    """

    name = "stooq"

    def _stooq_symbol(self, symbol: str) -> str:
        if symbol.endswith((".NS", ".BO")):
            raise ValueError("Stooq does not carry NSE/BSE tickers")
        if symbol.endswith("-USD"):
            return symbol.replace("-USD", "").lower() + "usd"
        return symbol.lower() + ".us"

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        if interval != "1d":
            raise ValueError(f"Stooq has no {interval} bars, only daily")
        code = self._stooq_symbol(symbol)
        url = (f"https://stooq.com/q/d/l/?s={code}&d1={start.replace('-', '')}"
               f"&d2={end.replace('-', '')}&i=d")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
        if "Date" not in raw.split("\n")[0]:
            raise RuntimeError(f"Stooq returned no data for {code}")
        df = pd.read_csv(io.StringIO(raw), parse_dates=["Date"], index_col="Date")
        df.columns = [c.lower() for c in df.columns]
        if "volume" not in df:
            df["volume"] = 0.0
        return df[["open", "high", "low", "close", "volume"]]


class CoinGeckoProvider:
    """Daily crypto bars. Free, no key, generous enough for a hundred assets.

    Only crypto — asking it for an equity raises rather than returning
    something plausible-looking, because a wrong answer that parses is worse
    than an error.
    """

    name = "coingecko"

    IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
           "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
           "LINK": "chainlink", "MATIC": "matic-network", "XRP": "ripple",
           "DOGE": "dogecoin", "LTC": "litecoin", "ATOM": "cosmos",
           "UNI": "uniswap", "AAVE": "aave", "OP": "optimism",
           "ARB": "arbitrum", "NEAR": "near", "APT": "aptos",
           "SUI": "sui", "TRX": "tron", "XLM": "stellar", "TIA": "celestia"}

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        if not symbol.endswith("-USD"):
            raise ValueError("CoinGecko carries crypto only")
        if interval != "1d":
            raise ValueError(f"this fallback provides daily bars, not {interval}")
        ticker = symbol.replace("-USD", "").upper()
        coin = self.IDS.get(ticker)
        if coin is None:
            raise ValueError(f"no CoinGecko id known for {ticker}")

        # This endpoint accepts only these window sizes. Passing 91 — which
        # is what a June-to-August range works out to — is rejected outright.
        # An earlier version computed the day count and sent it, which is why
        # every CoinGecko fetch failed while the API itself was fine.
        allowed = (1, 7, 14, 30, 90, 180, 365)
        wanted = max((pd.Timestamp(end) - pd.Timestamp(start)).days, 1)
        days = next((d for d in allowed if d >= wanted), 365)
        url = (f"https://api.coingecko.com/api/v3/coins/{coin}/ohlc"
               f"?vs_currency=usd&days={days}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            import json

            rows = json.loads(resp.read().decode("utf-8"))
        if not rows:
            raise RuntimeError(f"CoinGecko returned nothing for {coin}")

        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
        df.index = pd.to_datetime(df.pop("ts"), unit="ms")
        # No volume from this endpoint. Zero is honest here: the screen's
        # liquidity criterion reads it and will score the asset down rather
        # than treating an invented number as measured.
        df["volume"] = 0.0
        return df.resample("1D").last().dropna()


class TwelveDataProvider:
    """Daily bars for US and NSE equities. Needs a free key.

    Free, keyless, server-friendly equity data covering both US and India is a
    combination that barely exists. Alpha Vantage allows 25 requests a day
    against the 100 this needs; Stooq blocks non-browsers. Twelve Data's free
    tier is 800 credits a day at 8 a minute, which fits.

    Absent a key this raises immediately rather than joining the chain, so the
    report shows Yahoo alone instead of implying a backup that cannot run.
    """

    name = "twelvedata"

    def __init__(self, key: str | None = None):
        import os

        self.key = key or os.environ.get("TWELVEDATA_KEY", "")

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        import json

        if not self.key:
            raise RuntimeError("TWELVEDATA_KEY is not set — no equity fallback")
        if symbol.endswith("-USD"):
            raise ValueError("crypto goes to CoinGecko, not here")

        bar = {"1d": "1day", "1h": "1h", "15m": "15min", "5m": "5min"}.get(interval)
        if bar is None:
            raise ValueError(f"unsupported interval {interval}")

        url = (f"https://api.twelvedata.com/time_series?symbol={symbol}"
               f"&interval={bar}&start_date={start}&end_date={end}"
               f"&outputsize=5000&apikey={self.key}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        # It reports errors in a 200 body, so the status alone proves nothing.
        if payload.get("status") == "error" or "values" not in payload:
            raise RuntimeError(payload.get("message", "no values returned"))

        df = pd.DataFrame(payload["values"])
        df.index = pd.to_datetime(df.pop("datetime"))
        for column in ("open", "high", "low", "close", "volume"):
            df[column] = pd.to_numeric(df.get(column, 0.0), errors="coerce")
        return df[["open", "high", "low", "close", "volume"]].sort_index().dropna()


@dataclass
class FallbackProvider:
    """Tries each provider in turn. Records every attempt.

    The order matters: the first is the one whose adjustment convention the
    stored history already follows. Falling back is a repair, not a preference.
    """

    providers: list[Provider]
    attempts: dict[str, list[Attempt]] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def default(cls) -> FallbackProvider:
        from .market import YahooProvider

        chain: list[Provider] = [YahooProvider()]
        twelve = TwelveDataProvider()
        if twelve.key:
            chain.append(twelve)
        chain += [CoinGeckoProvider(), StooqProvider()]
        return cls(chain)

    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        log: list[Attempt] = []
        for provider in self.providers:
            name = getattr(provider, "name", type(provider).__name__)
            try:
                df = provider.history(symbol, start, end, interval)
            except Exception as exc:  # noqa: BLE001  # handled: recorded in the attempt log, which report() prints and the final RuntimeError repeats
                log.append(Attempt(name, False, f"{type(exc).__name__}: {exc}"))
                continue

            if df is None or df.empty:
                log.append(Attempt(name, False, "returned no rows"))
                continue

            # A provider that answers with impossible bars has not answered.
            # Accepting them would put the fallback's worst output into the
            # store under the same name as the best.
            report = verify(df, symbol)
            if report.problems:
                log.append(Attempt(name, False,
                                   f"failed integrity: {report.problems[0]}"))
                continue

            log.append(Attempt(name, True, rows=len(df)))
            self.attempts[symbol] = log
            previous = self.sources.get(symbol)
            if previous and previous != name:
                record_skip("source_changed", symbol,
                            RuntimeError(f"history now coming from {name}, "
                                         f"previously {previous} — returns "
                                         "across the switch are partly an "
                                         "artifact of the change"))
            self.sources[symbol] = name
            return df

        self.attempts[symbol] = log
        detail = "; ".join(f"{a.provider}: {a.reason}" for a in log)
        raise RuntimeError(f"every source failed for {symbol} — {detail}")

    # ------------------------------------------------------------ reporting
    def stitched(self) -> list[str]:
        """Symbols whose history has come from more than one source."""
        return sorted(s for s, log in self.attempts.items()
                      if sum(1 for a in log if a.ok) and
                      any(not a.ok for a in log))

    def report(self) -> str:
        if not self.attempts:
            return "No fetches yet."
        by_source: dict[str, int] = {}
        failed: list[str] = []
        for symbol, log in self.attempts.items():
            winner = next((a.provider for a in log if a.ok), None)
            if winner is None:
                failed.append(symbol)
            else:
                by_source[winner] = by_source.get(winner, 0) + 1

        lines = [f"{len(self.attempts)} symbol(s) fetched:"]
        lines += [f"  {src}: {n}" for src, n in sorted(by_source.items(),
                                                       key=lambda kv: -kv[1])]
        if failed:
            lines.append(f"  no source worked: {', '.join(failed[:8])}"
                         + (f" and {len(failed) - 8} more" if len(failed) > 8 else ""))
        fallen_back = [s for s, log in self.attempts.items()
                       if log and not log[0].ok and any(a.ok for a in log)]
        if fallen_back:
            lines.append(f"\n{len(fallen_back)} symbol(s) came from a fallback. "
                         "Their bars use a different adjustment convention, so a "
                         "return computed across the switch is partly an artifact "
                         "of the change, not a move in the market.")
        return "\n".join(lines)
