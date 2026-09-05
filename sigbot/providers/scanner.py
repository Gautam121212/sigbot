"""Building the candidate pool from the market, not from a list I typed.

The 156 candidates were hardcoded. They skew US large-cap because those are the
tickers I knew had clean history — 104 US equities against 25 Indian ones, for
someone trading from Delhi. That is not a screen finding the best assets; it is
a screen finding the best of my guesses.

## Why this is cheap

The obvious approach is to download two years of bars for every candidate and
let the screen decide. Two thousand symbols at Yahoo's throttle is over an hour
and a real chance of being blocked partway.

But the exchange listings already carry what the first cut needs. NSE's equity
CSV has the series and listing date; Nasdaq's screener JSON has market cap and
volume; CoinGecko's markets endpoint has cap and 24h volume. So the wide filter
costs three HTTP requests, not two thousand, and only survivors get downloaded.

## Which criteria a wide pool improves, and which it breaks

Structural criteria — liquidity, movability, stability, reactivity — measure a
property. An asset trading 50m shares a day is liquid, not luckily liquid.
Widening the pool makes those strictly better.

`backtested` is different. Running a walk-forward across two thousand assets
and keeping the best hundred is two thousand hypotheses with no correction:
some show skill by chance, those are exactly the ones scoring highest, and the
screen hands back a board selected for luck. That is the failure `contagion.py`
already corrects with Benjamini-Hochberg and the screener does not.

So this module deliberately stops at a shortlist. It does not rank on
performance. Handing a wide pool to an uncorrected performance criterion would
make the board worse while making it look better researched.

Honest constraint: the listing endpoints are not verified from here — this
sandbox allows a short domain list and every one of these returned 403.
`scripts/check_universe.py` answers whether they work from your machine.

Largest risk: that a bigger pool feels like better selection. It is a better
starting set. Whether the screen picks well from it is the screen's problem,
and `track_record` — the criterion that would make that adaptive — is still
flat at 5/10 on every asset because nothing has a live record yet.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
from dataclasses import dataclass, field

from ..skips import record_skip

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")

# Deliberately generous. The screen does the real work; this only removes what
# cannot possibly answer — something too thin to trade or too new to have the
# history `stability` needs across both halves.
MIN_MARKET_CAP = 500_000_000        # USD
MIN_DAILY_VOLUME = 200_000          # shares or USD, depending on the source


@dataclass
class Candidate:
    symbol: str
    name: str
    kind: str
    exchange: str
    market_cap: float = 0.0
    volume: float = 0.0


@dataclass
class Universe:
    candidates: list[Candidate] = field(default_factory=list)
    attempted: dict[str, int] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    def by_exchange(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.candidates:
            out[c.exchange] = out.get(c.exchange, 0) + 1
        return out


def _get(url: str, timeout: float = 45.0) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/csv,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# NSE's own index constituents, already filtered on market cap and traded
# value. The full equity CSV carries no volume, and taking its first N rows
# means taking companies alphabetically: three hundred names beginning with A,
# most listed months ago. That is how a screen ends up proposing AAATECH and
# AGRITECH over your entire board.
NSE_INDEX_LISTS = (
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
)


def nse_equities(limit: int = 400) -> list[Candidate]:
    """India's larger listed equities, from NSE's own index constituents.

    The index is the liquidity screen: NSE has already applied market cap and
    traded-value thresholds to build it, which is the filter the raw equity
    CSV gave no way to apply.
    """
    last_error: Exception | None = None
    for url in NSE_INDEX_LISTS:
        try:
            raw = _get(url)
        except Exception as exc:  # noqa: BLE001  # handled: falls through to the next index, and raises with the last reason if all fail
            last_error = exc
            continue
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))
        out = [
            Candidate(f"{(r.get('Symbol') or '').strip()}.NS",
                      (r.get("Company Name") or "").strip(), "equity", "NSE")
            for r in rows if (r.get("Symbol") or "").strip()
        ]
        if out:
            return out[:limit]
    raise RuntimeError(f"no NSE index list responded — last: {last_error}")


def nasdaq_equities(limit: int = 400) -> list[Candidate]:
    """US equities with cap and volume, from Nasdaq's screener endpoint.

    This one carries the numbers, so the cut is real rather than structural.
    """
    raw = _get("https://api.nasdaq.com/api/screener/stocks"
               "?tableonly=true&limit=5000&download=true")
    payload = json.loads(raw.decode("utf-8", "replace"))
    rows = (payload.get("data") or {}).get("rows") or []
    if not rows:
        raise RuntimeError("Nasdaq returned no rows")

    out: list[Candidate] = []
    for row in rows:
        symbol = (row.get("symbol") or "").strip()
        if not symbol or not symbol.isalpha():
            continue                       # skip warrants, units, preferreds
        cap = _number(row.get("marketCap"))
        volume = _number(row.get("volume"))
        if cap < MIN_MARKET_CAP or volume < MIN_DAILY_VOLUME:
            continue
        out.append(Candidate(symbol, (row.get("name") or "").strip(),
                             "equity", "NASDAQ", cap, volume))
    out.sort(key=lambda c: -c.volume)
    return out[:limit]


# Pegged to a dollar, so movability is zero by construction. CoinGecko sorted
# by volume puts them near the top because they are the settlement layer, and
# every one of them wastes a download and a slot in the ranking.
STABLECOINS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDD", "FDUSD", "PYUSD", "USDE",
    "USDS", "FRAX", "LUSD", "GUSD", "USDP", "EURC", "EURS", "RLUSD", "USD1",
}


def crypto(limit: int = 60) -> list[Candidate]:
    """Crypto by 24h volume, from CoinGecko — the one fallback already proven
    to answer from your machine."""
    raw = _get("https://api.coingecko.com/api/v3/coins/markets"
               "?vs_currency=usd&order=volume_desc&per_page=100&page=1")
    rows = json.loads(raw.decode("utf-8", "replace"))
    out: list[Candidate] = []
    for row in rows:
        ticker = (row.get("symbol") or "").upper()
        label = (row.get("name") or "").lower()
        # The hardcoded list goes stale the moment someone launches another
        # one — USDG slipped through it. A name rule catches the ones nobody
        # has heard of yet, which is most of them.
        # Any of these on their own. An earlier version required "usd" in the
        # name AND a peg word, so "Some Stable Dollar" passed — the conjunction
        # made the rule narrower than the hardcoded list it was meant to widen.
        pegged = (ticker in STABLECOINS
                  or ticker.startswith("USD") or ticker.endswith("USD")
                  or any(word in label for word in
                         ("dollar", "stablecoin", "stable coin", "pegged",
                          "usd", "euro coin", "tether")))
        if not ticker or pegged:
            continue
        # Wrapped and staked wrappers track their underlying, so they add a
        # near-duplicate series rather than a new asset.
        if ticker.startswith(("W", "ST")) and ticker[1:] in ("BTC", "ETH"):
            continue
        cap = float(row.get("market_cap") or 0)
        volume = float(row.get("total_volume") or 0)
        if cap < MIN_MARKET_CAP or volume < MIN_DAILY_VOLUME:
            continue
        out.append(Candidate(f"{ticker}-USD", row.get("name") or ticker,
                             "crypto", "CRYPTO", cap, volume))
    return out[:limit]


def _number(value) -> float:
    if value in (None, "", "NA"):
        return 0.0
    text = str(value).replace("$", "").replace(",", "").strip()
    multiplier = 1.0
    if text.endswith("B"):
        multiplier, text = 1e9, text[:-1]
    elif text.endswith("M"):
        multiplier, text = 1e6, text[:-1]
    elif text.endswith("K"):
        multiplier, text = 1e3, text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return 0.0


def build(nse: int = 300, us: int = 250, coins: int = 50) -> Universe:
    """Assemble the candidate pool. One request per source, not one per symbol.

    A source that fails is recorded and the others still run: losing US names
    should not cost you the Indian ones, and a pool silently short of a whole
    exchange would look like a screen that simply preferred elsewhere.
    """
    universe = Universe()
    for name, fetch, want in (("nse", nse_equities, nse),
                              ("nasdaq", nasdaq_equities, us),
                              ("crypto", crypto, coins)):
        try:
            found = fetch(want)
        except Exception as exc:  # noqa: BLE001  # handled: recorded per source, and the others still run
            universe.failures[name] = f"{type(exc).__name__}: {exc}"
            record_skip("universe", name, exc)
            continue
        universe.attempted[name] = len(found)
        universe.candidates.extend(found)
    return universe


def describe(universe: Universe) -> str:
    lines = [f"{len(universe.candidates)} candidate(s):"]
    for exchange, count in sorted(universe.by_exchange().items(),
                                  key=lambda kv: -kv[1]):
        lines.append(f"  {exchange:<10} {count}")
    for source, reason in universe.failures.items():
        lines.append(f"  {source} FAILED — {reason}")
    if universe.failures:
        lines.append("\nA missing source is not a screen that preferred "
                     "elsewhere. Assets from it were never considered.")
    lines.append("\nThis is a starting set, not a ranking. The screen decides "
                 "what earns a slot, and it does not rank on backtested skill "
                 "across a pool this size — running a walk-forward on hundreds "
                 "of assets and keeping the winners selects for luck.")
    return "\n".join(lines)
