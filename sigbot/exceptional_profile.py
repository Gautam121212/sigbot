"""Exceptional-profile screener — the DNA of 10-baggers, honestly bounded.

Deep research reverse-engineered every stock that gained 300%+ in 2 years. The
DNA: hypergrowth (>50% rev growth) + high margin (>60%) + unprofitable (burning
cash to grow). This profile concentrates 10-baggers at 4.9% vs 1.3% baseline —
a 3.8x lift, the software power-law at the extreme.

THE HONEST BOUND: a basket of this profile still averages only ~7%/yr (41% win),
because 59% lose and no filter in free data separates the winners ex-ante — which
company executes into a 10-bagger depends on product/TAM/luck the data can't see.

So this screener is NOT a path to exceptional returns ON ITS OWN. It is the
correct universe (where 10-baggers concentrate), and the exceptional return only
comes from (a) alt-data that separates winners early — which sigbot lacks, or
(b) the crypto small-cap inefficiency once forward-validated. This is documented
plainly so the model never pretends a 7% screen is a 20% edge.
"""
from __future__ import annotations

from dataclasses import dataclass

HYPERGROWTH = 0.50
HIGH_MARGIN = 0.60
# Measured, cleaned (2015-2023):
TENBAGGER_RATE = 0.049      # of the profile, become 10-baggers in 2y
BASELINE_RATE = 0.013
BASKET_AVG_RETURN = 0.07    # the honest ceiling of a diversified basket
DOUBLE_RATE = 0.11


@dataclass(frozen=True)
class ProfileRead:
    is_exceptional_profile: bool
    tenbagger_odds: float      # vs baseline
    note: str


def exceptional_profile(revenue_growth_yoy: float | None,
                        gross_margin: float | None,
                        operating_margin: float | None) -> ProfileRead:
    """Whether a company has the 10-bagger DNA. It marks the right universe —
    NOT a prediction that this specific name wins (the data can't tell which)."""
    if None in (revenue_growth_yoy, gross_margin, operating_margin):
        return ProfileRead(False, 0.0, "missing fundamentals")
    is_profile = (revenue_growth_yoy >= HYPERGROWTH        # type: ignore[operator]
                  and gross_margin >= HIGH_MARGIN          # type: ignore[operator]
                  and operating_margin < 0)                # type: ignore[operator]
    if is_profile:
        return ProfileRead(
            True, round(TENBAGGER_RATE / BASELINE_RATE, 1),
            f"10-bagger DNA (hypergrowth + high margin + burning cash) — "
            f"{TENBAGGER_RATE:.0%} become 10-baggers ({TENBAGGER_RATE / BASELINE_RATE:.1f}x "
            f"baseline), but the basket averages ~{BASKET_AVG_RETURN:.0%}/yr; "
            "which one wins needs data beyond fundamentals.")
    return ProfileRead(False, 0.0, "not the exceptional profile")


def honest_ceiling() -> str:
    """The plain truth about free-data returns, so nothing overclaims."""
    return ("Free public data (price + fundamentals + filings) tops out near "
            "7-10%/yr for a diversified systematic book — that is market "
            "efficiency, not a research gap. Exceptional (15-25%) needs alt-data "
            "the market lacks, the crypto small-cap inefficiency (forward-"
            "validated), or leverage. No RSI/margin/catalyst combo on free data "
            "yields 20% — it would already be arbitraged.")
