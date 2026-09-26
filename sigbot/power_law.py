"""Power-law portfolio model for ventures and ideas — the professional playbook.

From experienced angels (researched, with hard numbers): venture returns follow
a power law, so the edge is NOT hit rate — it is OUTLIER EXPOSURE across enough
bets. The base rates the pros quote:
  ~30% of bets fail (return <1x)
  ~35% return 1-3x (modest)
  ~28% return 3-10x (good)
  ~7% return 10x+ (the outliers that drive everything)

The single most important number: you need ~20 bets for a 64% chance of catching
a 50x outlier (10 bets = 40%, 5 bets = 23%). Below 20, a missed outlier defines
your whole record. So ventures/ideas are a PORTFOLIO game, not a single-pick game.

This model sizes the venture sleeve accordingly: enough small bets to catch the
power law, each capped, with follow-on reserve for the winners. It does not
predict which venture wins — it guarantees enough shots that one likely does.
"""
from __future__ import annotations

from dataclasses import dataclass

# The professional base rates (fractions that must sum to 1).
FAIL_RATE = 0.30            # <1x
MODEST_RATE = 0.35         # 1-3x
GOOD_RATE = 0.28           # 3-10x
OUTLIER_RATE = 0.07        # 10x+

MIN_BETS = 20              # the professional threshold for power-law protection
FOLLOW_ON_RESERVE = 0.40   # 40% of capital held back to double down on winners


@dataclass(frozen=True)
class PortfolioPlan:
    n_bets: int
    protected: bool          # enough bets to catch the power law?
    outlier_probability: float
    per_bet_pct: float       # % of the venture sleeve per initial bet
    note: str


def outlier_probability(n_bets: int, single_hit: float = 0.05) -> float:
    """Probability of at least one big outlier across n independent bets, where
    each bet has `single_hit` chance of being one. This is the number that makes
    20 bets the threshold: 1 - (1 - 0.05)^20 = 64%."""
    return 1 - (1 - single_hit) ** max(n_bets, 0)


def plan(n_available: int, sleeve_pct: float = 0.10) -> PortfolioPlan:
    """How to deploy a venture/ideas sleeve given how many real bets are on
    offer. sleeve_pct is the share of the whole account for ventures (small —
    the rest stays in the proven models)."""
    n = n_available
    protected = n >= MIN_BETS
    # Initial capital is (1 - reserve) of the sleeve, spread across the bets.
    deployable = 1 - FOLLOW_ON_RESERVE
    per_bet = (deployable / n * 100) if n else 0.0
    prob = outlier_probability(n)
    if not protected:
        note = (f"only {n} bets — power law NOT protected "
                f"({prob:.0%} chance of an outlier; need {MIN_BETS}+ for 64%). "
                "A missed outlier would define the record.")
    else:
        note = (f"{n} bets — power-law protected ({prob:.0%} outlier odds), "
                f"{per_bet:.1f}% of the venture sleeve each, "
                f"{FOLLOW_ON_RESERVE:.0%} held for follow-on into winners.")
    return PortfolioPlan(n, protected, round(prob, 3), round(per_bet, 2), note)


def is_worth_running(n_available: int) -> bool:
    """The venture/ideas model is only worth deploying capital to once there are
    enough real bets to make the power law work. Below that, it is gambling."""
    return n_available >= MIN_BETS
