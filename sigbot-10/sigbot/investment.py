"""Investment opportunity diligence — IPOs, token listings, funds, anything.

## The design decision that shapes this module

You described the input as: *a source says this is a good investment, here is the
return they say it can earn — rate it.*

That description is also, almost exactly, the shape of a promotion. Unsolicited
claims of expected return on new listings are the highest-fraud-density category
in retail finance, and a system that ingests "sources say this can return 300%"
and emits a rating is a machine for laundering marketing into analysis.

So this module inverts the input. **A stated expected return is scored as a
negative signal, not a positive one.** Audited prospectuses do not promise
returns; promotional material does. The `claimed_return` field exists solely to
record the claim and raise a flag — it never contributes positively to a score.

## What is actually rateable

A new listing has no price history. There is nothing to measure and nothing to
backtest, so there is no honest way to produce a probability of profit. What
*can* be assessed, consistently and from public information, is the quality of
the evidence and the presence of structural hazards. That is what the score is:
**a diligence rating, not a return forecast.**

A high score means "the disclosures are real, the incentives are visible and the
exit exists" — it does not mean the investment will make money. A low score
means "you cannot evaluate this from what is available", which is a sufficient
reason to pass without any view on the underlying asset.

## Fatal flags override the score

Some findings make the rest irrelevant. A guaranteed return, an anonymous team
controlling funds, or an unregistered offering caps the rating regardless of how
polished everything else looks — because polish is cheap and those three are
what the polish is usually for.
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .reference_class import ClaimAssessment, ReferenceClass, assess_claim


class AssetClass(str, Enum):
    IPO = "IPO"
    TOKEN = "TOKEN"                # ICO, IDO, new listing
    FUND = "FUND"                  # mutual fund, PMS, AIF, ETF
    LISTED_EQUITY = "LISTED_EQUITY"
    CRYPTO = "CRYPTO"              # established, traded
    PRIVATE = "PRIVATE"            # angel, pre-IPO, unlisted
    OTHER = "OTHER"


class Severity(str, Enum):
    FATAL = "FATAL"        # caps the rating at 15
    SEVERE = "SEVERE"      # caps the rating at 40
    MODERATE = "MODERATE"  # -8 points each


CAPS = {Severity.FATAL: 15.0, Severity.SEVERE: 40.0}
MODERATE_PENALTY = 8.0

# flag key -> (severity, what it means, why it matters)
RED_FLAGS: dict[str, tuple[Severity, str, str]] = {
    "guaranteed_return": (
        Severity.FATAL, "a guaranteed or 'assured' return is stated",
        "no honest investment guarantees a return; in most jurisdictions saying so "
        "is itself an offence",
    ),
    "anonymous_principals": (
        Severity.FATAL, "the people controlling the money are not publicly identifiable",
        "there is no one to sue, regulate, or hold responsible",
    ),
    "unregistered_offering": (
        Severity.FATAL, "the offering is not registered with any regulator that covers it",
        "no disclosure obligation means the disclosures are whatever they choose",
    ),
    "pays_earlier_investors": (
        Severity.FATAL, "returns are funded by new inflows rather than operations",
        "this is the definition of the structure, whatever it is called",
    ),
    "promoter_is_the_source": (
        Severity.SEVERE, "the source recommending it is paid by, or sells, the thing",
        "the recommendation is advertising with a byline",
    ),
    "no_audited_financials": (
        Severity.SEVERE, "no independently audited financial statements exist",
        "unaudited numbers are assertions, not evidence",
    ),
    "urgency_pressure": (
        Severity.SEVERE, "closing soon / limited allocation / act now",
        "time pressure exists to prevent the diligence you are doing right now",
    ),
    "claimed_return_stated": (
        Severity.SEVERE, "a specific expected return was quoted to you",
        "prospectuses forecast risk; promotions forecast returns",
    ),
    "insider_concentration": (
        Severity.MODERATE, "insiders hold a large share with a short or absent lock-up",
        "they can exit into your liquidity",
    ),
    "proceeds_to_selling_holders": (
        Severity.MODERATE, "the raise mostly cashes out existing holders, not growth",
        "the people who know it best are reducing exposure",
    ),
    "no_valuation_basis": (
        Severity.MODERATE, "nothing to value it against — no revenue, no assets, no yield",
        "price becomes narrative, and narrative reprices fast",
    ),
    "thin_liquidity": (
        Severity.MODERATE, "little secondary volume or a long lock-up before exit",
        "an entry without an exit is a donation with extra steps",
    ),
    "jurisdiction_barrier": (
        Severity.MODERATE, "an Indian resident cannot straightforwardly buy or exit it",
        "LRS limits, FEMA rules, VDA taxation or platform restrictions may apply",
    ),
    "single_source": (
        Severity.MODERATE, "only one outlet or channel is reporting it",
        "corroboration is the cheapest fraud filter there is",
    ),
}

# criterion -> (weight, question)
DILIGENCE: dict[str, tuple[float, str]] = {
    "disclosure_quality": (20.0, "Are there audited financials, a filed prospectus, or "
                                 "on-chain verifiable data — as opposed to a deck?"),
    "source_independence": (16.0, "Is the information from someone with nothing to gain "
                                  "from your participation?"),
    "operating_history": (14.0, "Is there a real operating record, or only a plan?"),
    "incentive_alignment": (13.0, "Lock-ups, fee structure, insider holdings — do the "
                                  "principals lose if you lose?"),
    "exit_liquidity": (12.0, "Can you sell, to whom, and how quickly?"),
    "valuation_basis": (10.0, "Is there any anchor — earnings, assets, yield, cashflow?"),
    "regulatory_standing": (8.0, "Registered where, supervised by whom, recourse if what?"),
    "accessibility": (7.0, "Can you legally and practically buy AND exit from India?"),
}


# Asset class -> the reference class its base rates come from. CRYPTO and OTHER
# are mapped too: leaving them out meant a claim on established crypto silently
# got no evaluation at all, which is the failure mode this feature exists to fix.
_ASSET_TO_REFERENCE: dict[AssetClass, ReferenceClass] = {
    AssetClass.IPO: ReferenceClass.IPO_3Y,
    AssetClass.TOKEN: ReferenceClass.NEW_TOKEN_1Y,
    AssetClass.LISTED_EQUITY: ReferenceClass.LISTED_LARGE_CAP_1Y,
    AssetClass.FUND: ReferenceClass.ACTIVE_FUND_5Y,
    AssetClass.PRIVATE: ReferenceClass.EARLY_STAGE_PRIVATE,
    AssetClass.CRYPTO: ReferenceClass.LISTED_LARGE_CAP_1Y,
    AssetClass.OTHER: ReferenceClass.LISTED_LARGE_CAP_1Y,
}

_MULTIPLE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX\u00d7]")
_HORIZON = re.compile(r"(\d+(?:\.\d+)?)\s*(years?|months?|yrs?|mos?|weeks?)", re.IGNORECASE)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_claimed_return(claim: str | None) -> tuple[float, float] | None:
    """Extract (total multiple, horizon in years) from a free-text claim.

    Handles '8x in 6 months', '300% over 2 years', '10X'. Returns None when no
    multiple can be read — silently defaulting would invent a claim that was
    never made.
    """
    if not claim:
        return None
    m = _MULTIPLE.search(claim)
    if m:
        multiple = float(m.group(1))
    else:
        pct = _PERCENT.search(claim)
        if not pct:
            return None
        multiple = 1.0 + float(pct.group(1)) / 100.0
    if multiple <= 1.0:
        return None

    h = _HORIZON.search(claim)
    if not h:
        return multiple, 1.0          # stated below as an assumption, not a fact
    amount, unit = float(h.group(1)), h.group(2).lower()
    if unit.startswith("w"):
        years = amount / 52.0
    elif unit.startswith("mo"):
        years = amount / 12.0
    else:
        years = amount
    return multiple, max(years, 1 / 52.0)


@dataclass
class InvestmentOpportunity:
    name: str
    asset_class: AssetClass
    thesis: str
    scores: dict[str, float]                    # DILIGENCE key -> 0..10
    flags: list[str] = field(default_factory=list)
    claimed_return: str | None = None           # recorded, never rewarded
    claim_source: str | None = None
    notes: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        missing = set(DILIGENCE) - set(self.scores)
        if missing:
            raise ValueError(
                f"every diligence item must be scored, missing: {sorted(missing)}. "
                "An unscored criterion is a silent 10."
            )
        for k, v in self.scores.items():
            if not 0 <= v <= 10:
                raise ValueError(f"{k}={v} out of range 0..10")
        unknown = set(self.flags) - set(RED_FLAGS)
        if unknown:
            raise ValueError(f"unknown red flags: {sorted(unknown)}")
        # A quoted return is itself a flag. Added automatically so it cannot be
        # omitted by whoever fills in the form.
        if self.claimed_return and "claimed_return_stated" not in self.flags:
            self.flags.append("claimed_return_stated")

    @property
    def base_score(self) -> float:
        return sum(self.scores[k] / 10.0 * DILIGENCE[k][0] for k in DILIGENCE)

    @property
    def severities(self) -> list[Severity]:
        return [RED_FLAGS[f][0] for f in self.flags]

    @property
    def rating(self) -> float:
        """Diligence rating 0-100 after penalties and caps."""
        score = self.base_score
        score -= MODERATE_PENALTY * self.severities.count(Severity.MODERATE)
        for sev in (Severity.FATAL, Severity.SEVERE):
            if sev in self.severities:
                score = min(score, CAPS[sev])
        return round(max(0.0, score), 1)

    @property
    def verdict(self) -> str:
        if Severity.FATAL in self.severities:
            return "DO NOT PROCEED"
        if Severity.SEVERE in self.severities:
            return "NOT EVALUABLE — treat as promotion until proven otherwise"
        if self.rating >= 70:
            return "EVALUABLE — the evidence supports forming your own view"
        if self.rating >= 45:
            return "WEAK EVIDENCE — proceed only with money you can lose entirely"
        return "INSUFFICIENT EVIDENCE — pass"

    @property
    def claim_assessment(self) -> ClaimAssessment | None:
        """Outside view on the claimed return: how often this class delivers it."""
        parsed = parse_claimed_return(self.claimed_return)
        ref = _ASSET_TO_REFERENCE.get(self.asset_class)
        if not parsed or ref is None:
            return None
        multiple, horizon = parsed
        try:
            return assess_claim(multiple, horizon, ref)
        except ValueError:
            return None

    @property
    def horizon_was_assumed(self) -> bool:
        return bool(self.claimed_return) and not _HORIZON.search(self.claimed_return or "")

    def unblocking_questions(self) -> list[str]:
        """What would have to be answered to raise the rating."""
        gaps = sorted(DILIGENCE, key=lambda k: (self.scores[k] / 10.0 - 1) * DILIGENCE[k][0])
        return [DILIGENCE[k][1] for k in gaps[:3]]

    def render(self) -> str:
        lines = [
            f"{self.name}  [{self.asset_class.value}]",
            f"  DILIGENCE RATING {self.rating:.0f}/100 — {self.verdict}",
            f"  thesis: {self.thesis}",
        ]
        if self.claimed_return:
            lines.append(
                f"  claimed return: \"{self.claimed_return}\""
                + (f" (per {self.claim_source})" if self.claim_source else "")
            )
            lines.append("     ^ recorded as a RED FLAG, not as evidence. A quoted "
                         "return figure is a property of the pitch, not the asset.")
            assessment = self.claim_assessment
            if assessment is not None:
                lines.append("  CLAIM EVALUATED against how often this class delivers it:")
                lines += [f"    {ln}" for ln in assessment.render().splitlines()]
                if self.horizon_was_assumed:
                    lines.append("    NOTE: no horizon was stated, so one year was assumed. "
                                 "A shorter horizon makes the claim rarer still.")
            else:
                lines.append("     could not read a multiple from that wording — "
                             "no base rate applied.")
        if self.flags:
            lines.append("  red flags:")
            for f in sorted(self.flags, key=lambda x: list(Severity).index(RED_FLAGS[x][0])):
                sev, what, why = RED_FLAGS[f]
                lines.append(f"    [{sev.value}] {what}")
                lines.append(f"            {why}")
        else:
            lines.append("  red flags: none of the checked hazards found")
        lines.append("  diligence detail:")
        for k, (w, _) in DILIGENCE.items():
            s = self.scores[k]
            bar = "█" * int(round(s)) + "·" * (10 - int(round(s)))
            lines.append(f"    {k:<21} {bar} {s:>4.1f}/10  (weight {w:>4.1f})")
            if k in self.notes:
                lines.append(f"        {self.notes[k]}")
        lines.append("  to raise this rating, answer:")
        lines += [f"    - {q}" for q in self.unblocking_questions()]
        if self.sources:
            lines += ["  sources:"] + [f"    - {s}" for s in self.sources]
        else:
            lines.append("  sources: none recorded — the rating rests on nothing checkable")
        lines.append("  This is a rating of the available EVIDENCE, not a forecast of "
                     "return. It is not investment advice.")
        return "\n".join(lines)

    def brief(self) -> str:
        flags = f" · {len(self.flags)} flag(s)" if self.flags else ""
        line = f"[{self.rating:>3.0f}] {self.name} ({self.asset_class.value}){flags} — {self.verdict}"
        a = self.claim_assessment
        if a is not None:
            line += (f"\n      claim {a.claimed_multiple:g}x/{a.horizon_years:g}y: reached by "
                     f"~{a.base_rate:.1%} of this class ({a.odds_against:.0f} to 1 against)")
        return line


CLASS_CHECKLIST: dict[AssetClass, tuple[str, ...]] = {
    AssetClass.IPO: (
        "Read the risk factors section of the prospectus before the summary.",
        "What share of proceeds goes to the company versus selling shareholders?",
        "When does the anchor/insider lock-up expire, and what free float exists after?",
        "Is the last reported quarter's growth accelerating or decelerating?",
    ),
    AssetClass.TOKEN: (
        "Who holds the keys, and is the team publicly identifiable and reachable?",
        "Full token supply schedule: what unlocks, when, and to whom?",
        "Is there an independent audit of the contract, and did anyone fix the findings?",
        "Is there revenue, or only token price? Those are different businesses.",
        "Under Indian rules, VDA gains are taxed at a flat rate with TDS on transfer.",
    ),
    AssetClass.FUND: (
        "Total expense ratio and any performance fee, including the hurdle and high-water mark.",
        "Is the track record the fund's, or the manager's from somewhere else?",
        "Exit load, lock-in, and redemption mechanics under stress.",
        "Who is the custodian, and is the auditor independent?",
    ),
    AssetClass.PRIVATE: (
        "What are the liquidation preferences, and where do you sit in them?",
        "What is the realistic exit, and in how many years?",
        "Is there any information right, or do you find out when they tell you?",
    ),
    AssetClass.CRYPTO: (
        "Where does the liquidity actually sit, and what happens if that venue halts?",
        "Custody: your keys or someone else's?",
        "Indian VDA taxation applies to gains, with TDS on transfers.",
    ),
    AssetClass.LISTED_EQUITY: (
        "Does the thesis depend on something not already in the price?",
        "What does the last annual report say that the news coverage did not?",
    ),
    AssetClass.OTHER: (
        "What is the legal wrapper, and who is on the other side of the trade?",
    ),
}


def checklist(asset_class: AssetClass) -> str:
    items = CLASS_CHECKLIST.get(asset_class, CLASS_CHECKLIST[AssetClass.OTHER])
    return "\n".join([f"Before acting on a {asset_class.value}:"] + [f"  - {i}" for i in items])


def render_digest(opportunities: list[InvestmentOpportunity]) -> str:
    if not opportunities:
        return "No investment opportunities surfaced in this window."
    ranked = sorted(opportunities, key=lambda o: -o.rating)
    detailed = [o for o in ranked if o.rating >= 70 and Severity.FATAL not in o.severities]
    rest = [o for o in ranked if o not in detailed]

    out = [f"Investment opportunities — {datetime.now(timezone.utc):%Y-%m-%d}",
           f"{len(ranked)} surfaced, {len(detailed)} with evidence worth reading.", ""]
    for o in detailed:
        out += [o.render(), "", checklist(o.asset_class), ""]
    claimed = [o for o in ranked if o.claim_assessment is not None]
    if claimed:
        out.append("--- Claimed returns, checked against base rates ---")
        for o in claimed:
            a = o.claim_assessment
            if a is None:          # recomputed property; do not assume it holds
                continue
            out.append(f"  {o.name}: \"{o.claimed_return}\" -> {a.verdict}")
            out.append(f"    ~{a.base_rate:.1%} of {a.reference.value} reach it "
                       f"({a.odds_against:.0f} to 1 against)")
        out.append("")
    if rest:
        out.append("--- Not developed further ---")
        out += [o.brief() for o in rest]
    out.append(textwrap.dedent("""
        Ratings describe evidence quality, not expected return. Nothing here is
        investment advice, and no rating should be read as a recommendation to buy."""))
    return "\n".join(out)
