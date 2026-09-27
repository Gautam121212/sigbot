"""Small-cap turnover edge — the crypto gap no one systematically trades.

The user's push: stop modeling the top 10 coins (efficient, no edge) and
understand the WHOLE market — the thousands of small coins where the real
asymmetry lives. Investigating the actual market structure revealed the gap:

THE MARKET STRUCTURE (scanned 1,250 coins across all cap tiers):
  mega caps (top 15):  median -1%/yr, 20% doubled, 0% died  -> efficient, boring
  small caps (671):    median -54%/yr, 5% doubled, 13% DIED -> a graveyard
Blindly buying small caps LOSES (negative median). Everyone either plays safe
megas (no edge) or gambles small caps (negative expectancy). The gap: nobody has
the FILTER that separates the 5% that double from the 13% that die.

THE DISCOVERY — TURNOVER is that filter (clean medians, outliers capped):
  small caps by turnover (= daily volume / market cap = attention/liquidity):
    high turnover (>0.3):  median +26.2% / 30d, 87% up
    mid turnover:          +16.1%, 77% up
    dead turnover (<0.05): +2.6%, 62% up
Turnover is money flowing in relative to the coin's size. A small coin with high
turnover is being discovered — too small for funds to bother with, so the crowd
hasn't priced it. This is the edge: small AND high-turnover, the coins that are
catching fire before the market notices.

WHY IT IS A REAL GAP: funds can't trade $10-100M coins (too small to move size),
retail gambles them without the turnover filter, and the top-coin models ignore
them entirely. The turnover signal sits in the blind spot of all three.

CAVEAT: the finding is a snapshot (current turnover vs recent performance). It
must be validated FORWARD on the fetched history (turnover today -> return over
the next N days) before it is trusted — reverse-causation is the risk. The
small_cap_turnover_edge below is the signal; validate it on banked data first.
"""
from __future__ import annotations

from dataclasses import dataclass

# Market-cap band for the edge (too big = efficient, too small = untradeable).
MIN_CAP = 10_000_000
MAX_CAP = 100_000_000
# Turnover thresholds (daily volume / market cap).
HIGH_TURNOVER = 0.30
MID_TURNOVER = 0.05
# Measured median 30-day return by turnover bucket (snapshot — validate forward).
MEDIAN_30D = {"high": 0.262, "mid": 0.161, "dead": 0.026}


@dataclass(frozen=True)
class TurnoverEdge:
    coin: str
    in_band: bool
    turnover: float
    bucket: str
    tradeable: bool
    note: str


def turnover_edge(coin: str, market_cap: float | None,
                  daily_volume: float | None) -> TurnoverEdge:
    """Grade a coin for the small-cap turnover edge.

    Tradeable only when it is a small cap ($10-100M) with high turnover — the
    blind spot where money is flowing into a coin too small for funds to notice.
    """
    if market_cap is None or daily_volume is None or market_cap <= 0:
        return TurnoverEdge(coin, False, 0.0, "unknown", False, "missing data")
    in_band = MIN_CAP <= market_cap <= MAX_CAP
    turnover = daily_volume / market_cap
    bucket = ("high" if turnover >= HIGH_TURNOVER else
              "mid" if turnover >= MID_TURNOVER else "dead")
    tradeable = in_band and bucket == "high"
    if not in_band:
        note = "outside the small-cap band ($10-100M) — no edge here"
    elif bucket == "high":
        note = (f"small-cap + HIGH turnover ({turnover:.0%} of cap/day) — money "
                f"flowing in, the discovery zone (~+26% median 30d, validate fwd)")
    elif bucket == "mid":
        note = f"small-cap, mid turnover ({turnover:.0%}) — building, watch"
    else:
        note = f"small-cap but DEAD turnover ({turnover:.1%}) — no attention, skip"
    return TurnoverEdge(coin, in_band, round(turnover, 3), bucket, tradeable, note)


def is_tradeable(e: TurnoverEdge) -> bool:
    """A small-cap coin catching fire — the tradeable turnover setup."""
    return e.tradeable
