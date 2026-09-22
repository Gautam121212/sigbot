"""Business and investment opportunities — ventures, not stocks.

WHAT THESE ARE
--------------
Real-world propositions: "open a tape factory in the Philippines — low setup
cost, government incentives", "Dubai residential property — strong migration
and yield signals". Not a ticker, not a price chart. Each is a THESIS with a
cost to enter, a plausible upside, and evidence of varying strength.

THE GATE IS ASYMMETRY, NOT PROOF — AND THAT IS THE POINT
--------------------------------------------------------
The stocks model rightly demands a proven statistical edge before it commits
capital, because it takes thousands of near-identical bets. A venture is the
opposite: few bets, each unique, none provable in advance. Applying the
stocks gate here would reject everything — which is exactly the complaint
that prompted this: "brutal gates not allowing risky investments through".

So opportunities use the professional discipline for exactly this situation —
Taleb's barbell and the venture-capital power law:

  * A bet is WORTH TAKING when its downside is CAPPED and SURVIVABLE and its
    upside is large — regardless of how likely it is. You do not need to know
    it will work; you need to know that being wrong won't ruin you.
  * Size by survivability: no single venture risks more than a small, fixed
    slice of capital, so a total loss is a scratch, not a wound.
  * Most will fail. A few pay for all of them. That is not a flaw to gate
    away; it is the shape of the return.

So risky ideas are SHOWN and LABELLED, never hidden. A "risky" label means
the evidence is thin, not that the bet is bad — a thin-evidence bet with a
5x upside and a survivable downside is precisely what this model is for.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Fraction of capital a single venture may risk. From the barbell: the whole
# speculative sleeve is small, and no one bet dominates it.
MAX_VENTURE_RISK = 0.02          # 2% of capital, worst case
SPECULATIVE_SLEEVE = 0.20        # ventures live inside a 20% sleeve; 80% stays safe

# A venture clears the gate when its expected value is positive under the
# barbell test: even a small success probability passes if the payoff is large
# and the loss is capped. EV multiple = p_success * upside - (1 - p) * 1.
# The bar for a capped-downside bet is POSITIVE expected value with genuine
# asymmetry — not a high hurdle, because a high hurdle is the "brutal gate"
# that rejects every survivable long shot. EV just over 1.0x means: risking $1
# returns more than $1 on average across many such bets, and the barbell says
# take it, small. The asymmetry floor keeps out coin-flips dressed as ventures.
MIN_EV_MULTIPLE = 1.05          # positive expected value, net of the stake
MIN_UPSIDE_MULTIPLE = 3.0       # at least 3x, or it is not asymmetric enough


@dataclass(frozen=True)
class Venture:
    title: str
    thesis: str
    upside_multiple: float        # plausible return on the amount risked
    p_success: float              # rough, evidence-based; uncertainty is fine
    evidence_strength: float      # 0-1: how well-supported the thesis is
    downside_capped: bool         # is the worst case a known, bounded loss?
    sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ev_multiple(self) -> float:
        """Expected value as a multiple of the amount risked (loss capped at 1)."""
        return self.p_success * self.upside_multiple - (1 - self.p_success)

    @property
    def risky(self) -> bool:
        """Risky = thin evidence OR low hit probability. NOT a reason to hide it."""
        return self.evidence_strength < 0.5 or self.p_success < 0.35

    @property
    def worth_taking(self) -> bool:
        """The barbell test: capped downside, asymmetric upside, positive EV.

        Deliberately NOT gated on evidence strength or probability alone — a
        long shot with a big enough payoff and a survivable loss passes. What
        it MUST have is a bounded downside; an uncapped loss is the one thing
        the barbell never accepts, however tempting the upside.
        """
        return (self.downside_capped
                and self.upside_multiple >= MIN_UPSIDE_MULTIPLE
                and self.ev_multiple >= MIN_EV_MULTIPLE)

    def risk_reasons(self) -> tuple[str, ...]:
        out = []
        if self.evidence_strength < 0.5:
            out.append(f"thin evidence ({self.evidence_strength:.0%} supported) "
                       "— sources suggest, none confirm")
        if self.p_success < 0.35:
            out.append(f"long odds (~{self.p_success:.0%} success) — most such "
                       "bets fail; the payoff has to carry it")
        if not self.downside_capped:
            out.append("UNCAPPED DOWNSIDE — cannot size safely; not worth taking "
                       "at any upside")
        return tuple(out)

    def verdict(self) -> str:
        if not self.downside_capped:
            return "AVOID — downside not bounded"
        if not self.worth_taking:
            return "PASS — upside too small for the uncertainty"
        return "WORTH A SMALL BET" + (" (RISKY)" if self.risky else "")


def size_bet(equity: float, v: Venture) -> float:
    """How much to risk on a venture that is worth taking. Never more than
    MAX_VENTURE_RISK of capital, so a total loss is survivable, and scaled down
    further when the evidence is thin."""
    if not v.worth_taking:
        return 0.0
    conviction = min(1.0, max(0.25, v.evidence_strength))
    return round(equity * MAX_VENTURE_RISK * conviction, 2)


def evaluate(ventures) -> list[Venture]:
    """Ventures sorted by expected value — best asymmetry first. Risky ones are
    kept and labelled, never dropped; only uncapped-downside ones are effectively
    parked at the bottom by their verdict."""
    return sorted(ventures, key=lambda v: (v.worth_taking, v.ev_multiple), reverse=True)
