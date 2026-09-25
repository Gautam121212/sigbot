"""Novel-signal discovery — try things, label them risky, send to the risky loop.

The user's instruction: try everything, and whatever is found is RISKY by
construction (novel, unproven), so it goes to the risky loop, never straight to
the trusted models. This is the on-ramp: a discovered signal is registered here
as a risky experiment, tracked, and only graduates if it earns its place.

A "discovery" is a signal sigbot can compute that no price-only system has —
because it draws on sigbot's own structure: its five-model ledger, its news
archive, its GDELT global-tone feed, its per-model accuracy history. These are
byproducts of sigbot running, not indicators anyone can copy.
"""
from __future__ import annotations

from dataclasses import dataclass

from .risk_learning import record_risky_bet


@dataclass(frozen=True)
class Discovery:
    name: str                   # short id, e.g. "news-attention-spike"
    source: str                 # which sigbot-only stream it draws on
    thesis: str                 # what it claims, in a sentence
    half1: float                # measured effect, first half (%)
    half2: float                # measured effect, second half (%)

    # An effect larger than this per few days is not an edge — it is corrupt
    # data (micro-prices, bad rows). The +3% "small-cap" result and the
    # +28,000% confirmation run were both this. A real edge is small.
    SANITY_MAX = 8.0

    @property
    def is_corruption(self) -> bool:
        """Too large to be a real edge — almost certainly bad data."""
        return max(abs(self.half1), abs(self.half2)) > self.SANITY_MAX

    @property
    def survives_out_of_sample(self) -> bool:
        """Both halves same sign, non-trivial, and NOT corruption-sized."""
        if self.is_corruption:
            return False
        return (self.half1 * self.half2 > 0
                and min(abs(self.half1), abs(self.half2)) >= 0.3)

    @property
    def verdict(self) -> str:
        if self.is_corruption:
            return "CORRUPT-DATA"        # too large to be real; bad data
        if self.survives_out_of_sample:
            return "RISKY-KEEP"          # consistent; track it in the risky loop
        return "DISCARD"                 # flips or trivial; not real


def register(disc: Discovery, path: str = "risk_loop.jsonl") -> str:
    """File a discovery to the risky loop if it survives, else report discard.

    A surviving discovery is logged as a risky bet with downside_capped=True
    (it only ever adjusts sizing, never bets the account) and no outcome yet —
    the loop tracks whether it actually pays as live data arrives.
    """
    if disc.is_corruption:
        return f"{disc.name}: CORRUPT-DATA — effect too large to be real "\
               f"(h1 {disc.half1:+.2f}%, h2 {disc.half2:+.2f}%); bad data, not an edge"
    if not disc.survives_out_of_sample:
        return f"{disc.name}: {disc.verdict} (half1 {disc.half1:+.2f}%, "\
               f"half2 {disc.half2:+.2f}% — does not survive out of sample)"
    ok = record_risky_bet(
        model=disc.source, category=f"discovery:{disc.name}",
        downside_capped=True, amount_risked_pct=0.0, outcome_multiple=None,
        note=f"{disc.thesis} | h1 {disc.half1:+.2f}% h2 {disc.half2:+.2f}%",
        path=path)
    return (f"{disc.name}: RISKY-KEEP — filed to the risky loop"
            if ok else f"{disc.name}: survives but risky-loop write failed")


# The discoveries tested so far, with their measured out-of-sample results.
# Honest record: most do NOT survive. That is the point — try everything, keep
# only what holds, and even that stays RISKY until it earns trust.
TESTED = (
    Discovery("cross-model-consensus", "ledger",
              "when sigbot's 5 models agree on direction, trust them more",
              -5.8, 0.0),        # too sparse (12 days) + wrong sign → discard
    Discovery("funding-level", "binance-futures",
              "high positive funding (crowded longs) precedes a drop",
              -1.45, 0.52),      # flips → discard
    Discovery("funding-acceleration", "binance-futures",
              "funding rising fast (crowding building) precedes a drop",
              -2.45, 1.27),      # flips → discard
    Discovery("smallcap-dip-rebound", "coingecko",
              "a 5% dip in an illiquid small-cap rebounds",
              46834.0, 111910.0),  # micro-price corruption — caught by SANITY_MAX
)
