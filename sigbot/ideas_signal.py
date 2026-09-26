"""Ideas structural signal — which catalysts precede real opportunities.

The user's push: do the structural pass for ideas too. The ideas model detected
opportunity KEYWORDS but had no signal for which catalysts actually PAY. Using
SEC 8-K event data (the catalyst feed), decomposed by event type and company
size, with survivorship handling.

MEASURED (US 8-K events, 2015-2026):
Catalyst TYPE predicts the chance of a 15%+ move in 10 days:
  earnings (2.02):            9.0%
  material agreement (1.01):  7.6%  (biggest absolute moves — partnerships, M&A)
  Reg FD (7.01):              7.5%
  other event (8.01):         6.4%
  exec change (5.02):         5.2%  (weakest — a new CEO rarely moves the stock)

And the recombination — catalyst × SIZE (material agreements):
  mid-cap (0.5-2B):  8.3%   <- the sweet spot: real news, room to run
  small (<500M):     6.8%
  large (2B+):       4.5%   <- too big to move much on one deal

So an opportunity is strongest when the catalyst is a material agreement or
earnings AND the company is small/mid-cap (room to run). An exec-change or a
mega-cap catalyst is weak. This weights the ideas model by what actually moves
stocks, instead of treating every opportunity keyword equally.
"""
from __future__ import annotations

from dataclasses import dataclass

# Chance of a 15%+ move in 10 days, by 8-K catalyst type.
CATALYST_STRENGTH = {
    "earnings": 0.090,
    "material_agreement": 0.076,
    "reg_fd": 0.075,
    "other_event": 0.064,
    "exec_change": 0.052,
}
# Size multiplier for material agreements (mid-cap is the sweet spot).
SIZE_BIG_MOVE = {"small": 0.068, "mid": 0.083, "large": 0.045}


@dataclass(frozen=True)
class IdeaStrength:
    catalyst: str
    big_move_prob: float       # chance of a 15%+ move
    strong: bool
    note: str


def _size_bucket(market_cap: float | None) -> str:
    if market_cap is None:
        return "unknown"
    if market_cap < 500e6:
        return "small"
    if market_cap < 2e9:
        return "mid"
    return "large"


def idea_strength(catalyst: str, market_cap: float | None = None) -> IdeaStrength:
    """How strong an opportunity is, from its catalyst type and company size."""
    base = CATALYST_STRENGTH.get(catalyst, 0.05)
    size = _size_bucket(market_cap)
    # For material agreements, size sharpens it (mid-cap sweet spot).
    if catalyst == "material_agreement" and size in SIZE_BIG_MOVE:
        prob = SIZE_BIG_MOVE[size]
    else:
        prob = base
    strong = prob >= 0.075 and size in ("small", "mid", "unknown")
    if catalyst == "exec_change":
        note = "exec change — a weak catalyst; a new CEO rarely moves the stock"
    elif size == "large":
        note = f"{catalyst} but large-cap — too big to move much on one event"
    elif strong:
        note = (f"{catalyst} on a {size}-cap — real news with room to run "
                f"({prob:.0%} chance of a 15%+ move)")
    else:
        note = f"{catalyst} on a {size}-cap — a moderate opportunity"
    return IdeaStrength(catalyst, round(prob, 3), strong, note)


def is_strong_opportunity(s: IdeaStrength) -> bool:
    """Worth surfacing as a real opportunity, not noise."""
    return s.strong
