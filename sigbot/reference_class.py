"""Reference classes and carry economics — the outside view on a claim.

Two tools, one for each of your corrections.

## 1. "Can it really do 8x?" — answered from base rates, not from the pitcher

You were right that flagging a claim is not the same as evaluating it. So this
module evaluates it, the only way it can be evaluated without a crystal ball:
by asking how often assets *of that kind* have actually delivered that multiple
over that horizon. This is the outside view. It does not require knowing
anything about the specific asset, which is exactly why it works on day one and
cannot be talked out of by a good story.

The reference data below is empirical and sourced:

**IPOs, 3 years post-listing.** Roughly two-thirds underperform the market, and
64% trail it by more than 10%. Outperformers are about 29% of the total, but
they win big: the top decile averages over 300% market-adjusted, the ninth
decile 75%, the eighth 25%. So a 4x market-adjusted outcome sits around the
90th percentile of all IPOs — and 8x sits well inside that top decile's tail.
(Nasdaq analysis of long-run IPO performance; Ritter 1991 and the subsequent
literature find three-to-five-year underperformance versus matched firms.)

**New tokens.** Of roughly 20.2 million tokens listed on GeckoTerminal between
mid-2021 and end-2025, 53.2% are no longer actively traded, with 11.6 million
of those deaths in 2025 alone. Most did not sustain trading for a year. A
"dead" classification here means near-zero volume, abandoned development and a
99%+ drawdown from the high — so the modal outcome for a new token is not a
poor return, it is total loss. (CoinGecko, *How many cryptocurrencies failed*,
Dec 2025 cutoff.)

The point of putting a claim next to these numbers is not that the claim is
impossible. It is that "8x" belongs to a tail whose base rate you can name, and
naming it changes how much you are willing to risk.

## 2. "Buy copper and store it" — the carry test

Your copper example is a good thesis and a bad trade, for a reason that has
nothing to do with whether the shortage is real.

For any *storable* commodity, the futures curve already encodes what the market
expects. If everyone can read the same shortage forecast, forward prices have
moved and the spot price has moved with them. What you would be buying is not
the shortage; it is the difference between the shortage and the shortage
already priced.

And holding physical costs money every day: warehousing, insurance, financing
the capital, purity verification, and the bid-ask you cross twice. Those add to
a **cost of carry**, and the price must rise by more than the carry before you
make anything. `carry_test()` computes that breakeven and compares it with what
the futures curve already implies. When futures sit below your breakeven, the
market is telling you that storage is uneconomic — you would need the market to
be wrong by more than your carry, not merely wrong.

This is why commodity theses usually get expressed through futures or producer
equities rather than warehouses. It is also why a correct forecast can still
lose money, which is the part that gets left out of the article.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReferenceClass(str, Enum):
    IPO_3Y = "IPO_3Y"
    NEW_TOKEN_1Y = "NEW_TOKEN_1Y"
    LISTED_LARGE_CAP_1Y = "LISTED_LARGE_CAP_1Y"
    ACTIVE_FUND_5Y = "ACTIVE_FUND_5Y"
    EARLY_STAGE_PRIVATE = "EARLY_STAGE_PRIVATE"


@dataclass(frozen=True)
class ClassData:
    horizon_years: float
    total_loss_rate: float | None       # P(near-total loss), where measured
    underperform_rate: float | None     # P(worse than the market)
    # multiple -> approximate share of the population that reached it or better
    exceedance: dict[float, float]
    source: str
    caveat: str


REFERENCE_DATA: dict[ReferenceClass, ClassData] = {
    ReferenceClass.IPO_3Y: ClassData(
        horizon_years=3.0,
        total_loss_rate=None,
        underperform_rate=0.66,
        exceedance={1.25: 0.29, 1.75: 0.20, 4.0: 0.10, 8.0: 0.03, 15.0: 0.01},
        source="Nasdaq long-run IPO study; Ritter (1991) and successors",
        caveat="market-adjusted, US-listed, and the top decile drives the average — "
               "the mean is not the experience of a randomly chosen IPO",
    ),
    ReferenceClass.NEW_TOKEN_1Y: ClassData(
        horizon_years=1.0,
        total_loss_rate=0.532,
        underperform_rate=None,
        exceedance={2.0: 0.08, 4.0: 0.03, 8.0: 0.012, 15.0: 0.005},
        source="CoinGecko, 20.2m tokens listed mid-2021 to end-2025, 53.2% no longer traded",
        caveat="'dead' means near-zero volume, abandoned development and a 99%+ "
               "drawdown; the modal outcome is total loss, not a poor return. "
               "Exceedance figures above are indicative, not from the same study.",
    ),
    ReferenceClass.LISTED_LARGE_CAP_1Y: ClassData(
        horizon_years=1.0, total_loss_rate=0.0, underperform_rate=0.50,
        exceedance={1.5: 0.10, 2.0: 0.03, 4.0: 0.002, 8.0: 0.0004},
        source="broad equity return distributions",
        caveat="large caps rarely multiply quickly; that is the trade-off for not "
               "going to zero",
    ),
    ReferenceClass.ACTIVE_FUND_5Y: ClassData(
        horizon_years=5.0, total_loss_rate=0.0, underperform_rate=0.80,
        exceedance={1.5: 0.30, 2.0: 0.10, 4.0: 0.01, 8.0: 0.001},
        source="persistent finding that most active funds trail their benchmark net of fees",
        caveat="fees compound against you; survivorship removes the worst funds "
               "from most published tables",
    ),
    ReferenceClass.EARLY_STAGE_PRIVATE: ClassData(
        horizon_years=7.0, total_loss_rate=0.60, underperform_rate=None,
        exceedance={3.0: 0.12, 8.0: 0.04, 20.0: 0.01},
        source="venture portfolio outcome distributions",
        caveat="professional VC returns rest on portfolio construction; a single "
               "position is not a diversified fund",
    ),
}


@dataclass
class ClaimAssessment:
    claimed_multiple: float
    horizon_years: float
    reference: ReferenceClass
    base_rate: float                  # P(reaching that multiple or better)
    total_loss_rate: float | None
    horizon_mismatch: bool
    notes: list[str] = field(default_factory=list)

    @property
    def odds_against(self) -> float:
        return (1 - self.base_rate) / self.base_rate if self.base_rate > 0 else float("inf")

    @property
    def verdict(self) -> str:
        if self.base_rate >= 0.20:
            return "ORDINARY — the claim is within the normal range for this class"
        if self.base_rate >= 0.05:
            return "OPTIMISTIC — reachable, but it is a minority outcome"
        if self.base_rate >= 0.01:
            return "TAIL OUTCOME — possible, and unlikely enough to size accordingly"
        return "EXTRAORDINARY — the claim sits outside the observed distribution"

    def render(self) -> str:
        d = REFERENCE_DATA[self.reference]
        lines = [
            f"Claim: {self.claimed_multiple:g}x over {self.horizon_years:g} year(s)",
            f"  reference class: {self.reference.value} ({d.source})",
            f"  historically reached by ~{self.base_rate:.1%} of this class "
            f"— roughly {self.odds_against:.0f} to 1 against",
            f"  VERDICT: {self.verdict}",
        ]
        if self.total_loss_rate:
            lines.append(f"  base rate of near-total loss in this class: "
                         f"{self.total_loss_rate:.1%}")
        if d.underperform_rate:
            lines.append(f"  share that simply underperform the market: "
                         f"{d.underperform_rate:.0%}")
        if self.horizon_mismatch:
            lines.append(f"  NOTE: the reference data covers {d.horizon_years:g} years "
                         f"and the claim covers {self.horizon_years:g}. A shorter horizon "
                         "makes a large multiple rarer, not commoner.")
        lines.append(f"  caveat on the data: {d.caveat}")
        lines += [f"  {n}" for n in self.notes]
        lines.append("  This is an outside view: how often assets of this kind have "
                     "done it, independent of the specific story.")
        return "\n".join(lines)


def assess_claim(claimed_multiple: float, horizon_years: float,
                 reference: ReferenceClass) -> ClaimAssessment:
    """Rate a claimed return against how often that class actually delivers it."""
    if claimed_multiple <= 1.0:
        raise ValueError("claimed_multiple is a total multiple (2.0 = doubling)")
    d = REFERENCE_DATA[reference]

    points = sorted(d.exceedance.items())
    if claimed_multiple <= points[0][0]:
        rate = points[0][1]
    elif claimed_multiple >= points[-1][0]:
        # Extrapolate the tail down rather than clamping: a bigger claim is rarer.
        rate = points[-1][1] * (points[-1][0] / claimed_multiple) ** 2
    else:
        for (m1, r1), (m2, r2) in zip(points, points[1:]):
            if m1 <= claimed_multiple <= m2:
                w = (claimed_multiple - m1) / (m2 - m1)
                rate = r1 + w * (r2 - r1)
                break

    notes = []
    mismatch = abs(horizon_years - d.horizon_years) > 0.25 * d.horizon_years
    if horizon_years < d.horizon_years:
        rate *= horizon_years / d.horizon_years   # less time, fewer reach it
        notes.append("base rate scaled down for the shorter horizon.")
    return ClaimAssessment(claimed_multiple, horizon_years, reference,
                           max(rate, 1e-5), d.total_loss_rate, mismatch, notes)


# =====================================================================
# Carry economics — for "buy it and store it" theses
# =====================================================================

@dataclass
class CarryTest:
    commodity: str
    spot_price: float
    horizon_years: float
    storage_pct_per_year: float      # warehousing as a share of value
    insurance_pct_per_year: float
    financing_pct_per_year: float    # your cost of capital, not the repo rate
    round_trip_spread_pct: float     # bid-ask plus handling, paid once
    futures_price: float | None = None   # forward price for that horizon, if known
    thesis_is_consensus: bool = True     # is the shortage already widely reported?

    @property
    def annual_carry(self) -> float:
        return (self.storage_pct_per_year + self.insurance_pct_per_year
                + self.financing_pct_per_year)

    @property
    def breakeven_price(self) -> float:
        """Price you need at the horizon merely to break even."""
        return (self.spot_price * (1 + self.annual_carry) ** self.horizon_years
                * (1 + self.round_trip_spread_pct))

    @property
    def breakeven_rise_pct(self) -> float:
        return self.breakeven_price / self.spot_price - 1.0

    @property
    def market_implied_rise_pct(self) -> float | None:
        if self.futures_price is None:
            return None
        return self.futures_price / self.spot_price - 1.0

    @property
    def edge_pct(self) -> float | None:
        """How far the market's own forward price sits above your breakeven."""
        m = self.market_implied_rise_pct
        return None if m is None else m - self.breakeven_rise_pct

    def render(self) -> str:
        lines = [
            f"Storage thesis: {self.commodity}, {self.horizon_years:g} year(s)",
            f"  spot {self.spot_price:,.2f}",
            f"  carry: storage {self.storage_pct_per_year:.1%} + insurance "
            f"{self.insurance_pct_per_year:.1%} + financing "
            f"{self.financing_pct_per_year:.1%} = {self.annual_carry:.1%}/yr",
            f"  plus {self.round_trip_spread_pct:.1%} round-trip spread and handling",
            f"  BREAKEVEN: price must reach {self.breakeven_price:,.2f} "
            f"({self.breakeven_rise_pct:+.1%}) just to lose nothing",
        ]
        m = self.market_implied_rise_pct
        if m is None:
            lines.append("  no forward price supplied — you are guessing whether the "
                         "market already agrees with you. Look it up before acting.")
        else:
            lines.append(f"  the futures curve already implies {m:+.1%} over this horizon")
            e = self.edge_pct
            if e is not None and e < 0:
                lines.append(f"  VERDICT: storage is UNECONOMIC. The forward price sits "
                             f"{-e:.1%} below your breakeven. Being right about the "
                             "shortage is not enough — the market must be wrong by more "
                             "than your carry.")
            else:
                lines.append(f"  VERDICT: the forward price clears your breakeven by "
                             f"{e:.1%}. Thin, but the trade exists.")
        if self.thesis_is_consensus:
            lines.append("  CROWDING: you described this as widely reported. A forecast "
                         "everyone can read is already in the spot price. What you would "
                         "be buying is the gap between the shortage and the shortage "
                         "already priced — which is much smaller than the shortage.")
        lines.append("  Practical note: physical storage means warehousing, security, "
                     "purity verification, GST, and finding a buyer. Most people express "
                     "a commodity view through futures or producer equities instead, "
                     "which changes the risks rather than removing them.")
        return "\n".join(lines)


def storage_thesis_questions(commodity: str) -> list[str]:
    """What has to be true before a store-it thesis is worth any money."""
    return [
        f"What is the forward curve for {commodity} at your horizon? "
        "Contango means the market already pays you to wait — and charges you for it.",
        "Who is on the other side selling to you at spot, and what do they know?",
        "Is the shortage a flow problem (mine outages, months) or a stock problem "
        "(structural deficit, years)? They have opposite price paths.",
        "What is the substitution threshold — at what price do buyers switch away, "
        "capping the upside your thesis depends on?",
        "What supply is currently uneconomic that this price would restart?",
        "How would you actually exit: to a refiner, a trader, an exchange warehouse?",
        "If you are wrong, what is the holding cost per month while you wait?",
    ]
