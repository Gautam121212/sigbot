"""Shared types. Kept free of I/O so everything here is trivially testable."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Sequence

import pandas as pd

Side = str  # "BUY" | "SELL" | "HOLD"


@dataclass(frozen=True)
class Asset:
    symbol: str          # provider symbol, e.g. "AAPL" or "BTC-USD"
    name: str
    kind: str            # "equity" | "crypto"
    aliases: tuple[str, ...] = ()
    description: str = ""    # one line a non-specialist can read

    def match_terms(self) -> tuple[str, ...]:
        base = self.symbol.split("-")[0]
        return tuple({self.name.lower(), base.lower(), *(a.lower() for a in self.aliases)})


@dataclass(frozen=True)
class Article:
    uid: str
    title: str
    summary: str
    url: str
    source: str
    published_at: datetime      # tz-aware UTC. Publication time, NOT ingest time.
    ingested_at: datetime


@dataclass
class NewsSignal:
    asset: Asset
    side: Side
    raw_score: float                 # -1..1 signed impact estimate
    magnitude_pct: float | None      # expected move, None until validated
    drivers: list[str]
    articles: list[Article]
    validated: bool                  # False => no probability may be published
    hit_rate: float | None = None    # empirical, from shadow log
    hit_rate_lower: float | None = None
    n_observed: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DailyForecast:
    asset: Asset
    as_of: pd.Timestamp              # last bar used (close of day t)
    last_close: float
    p_up: float                      # calibrated P(next-day close > today close)
    p_up_lower: float                # reliability-bin lower bound
    expected_move_pct: float         # signed, from conditional empirical distribution
    q10_pct: float
    q90_pct: float
    side: Side
    reasons: list[str]
    n_calib_bin: int
    warnings: list[str] = field(default_factory=list)


class MarketDataProvider(Protocol):
    def history(self, symbol: str, start: str, end: str,
                interval: str = "1d") -> pd.DataFrame:
        """Return OHLCV indexed by tz-naive date, columns open/high/low/close/volume.

        Must be point-in-time honest: no forward-filled future rows, no
        survivorship filtering, no adjustment that leaks future splits into
        past bars beyond what was knowable. See README for provider caveats.
        """
        ...


class NewsProvider(Protocol):
    def fetch(self, since: datetime) -> Sequence[Article]: ...


class Messenger(Protocol):
    def send(self, text: str) -> None: ...
