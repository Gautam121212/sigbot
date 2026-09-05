"""Business opportunity scoring and plan generation.

A note on why this module is different from every other one in this repo, and
why it is allowed to produce a score where the trading models are not.

Markets price securities. When you spot that cybersecurity is booming, so has
everyone with a Bloomberg terminal, and the price already reflects it — which
is why the trading side of this project keeps returning "no edge". **Markets do
not price business opportunities.** Nobody has arbitraged away "mid-size firms
in Delhi need SOC2 readiness help and there are four consultants serving them".
The inefficiency there is enormous and durable, because capturing it requires
someone to actually do work rather than place an order.

So the asymmetry runs the other way here, and this is the part of your system
most likely to produce income.

What the score is: a structured judgment against a fixed rubric, applied
consistently, with every input visible. What it is not: an empirical
probability. There is no population of comparable ventures to compute a
frequency over, so the score cannot be calibrated the way a hit rate can. It is
a way of forcing the same nine questions at every opportunity instead of being
swayed by whichever one arrives with the most exciting headline.

The rubric weights the things that actually kill small ventures. Note what
carries the most weight: not market size, not how exciting the trend is, but
**distribution** — whether you can reach a paying customer — and **time to first
revenue**. Most failed small businesses had a real market and no route to it.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone

# name -> (weight, question, what a 10 looks like, what a 0 looks like)
RUBRIC: dict[str, tuple[float, str, str, str]] = {
    "demand_evidence": (
        18.0,
        "Is someone already paying for a worse version of this?",
        "named buyers with budgets, or an existing paid competitor with waitlists",
        "a trend article and an assumption that demand follows",
    ),
    "distribution": (
        18.0,
        "Can you reach a paying customer in the first 60 days without paid ads?",
        "you already know or can cold-reach the buyer; a channel exists",
        "you would need to build an audience first",
    ),
    "time_to_first_revenue": (
        14.0,
        "How long until the first rupee lands?",
        "under 30 days — service, consulting, or resale",
        "over a year — hardware, regulated product, or platform needing scale",
    ),
    "capital_required": (
        12.0,
        "What must you spend before revenue?",
        "under a lakh; laptop and time",
        "seven figures, inventory, or licences before the first sale",
    ),
    "skill_fit": (
        12.0,
        "Can you do the work, or learn it in under 3 months?",
        "adjacent to what you already do",
        "needs a licensed profession or years of domain apprenticeship",
    ),
    "competition_density": (
        10.0,
        "How crowded is the specific niche, not the broad market?",
        "few credible operators serving this exact segment",
        "commoditised, price-driven, many well-funded incumbents",
    ),
    "regulatory_friction": (
        8.0,
        "What licences, compliance or cross-border rules apply?",
        "none beyond ordinary business registration",
        "sectoral licence, data-residency rules, or FEMA/LRS exposure",
    ),
    "durability": (
        5.0,
        "If it works, what stops the next person copying it in a month?",
        "relationships, data, switching costs, or accumulated reputation",
        "nothing; it is a arbitrage anyone can run",
    ),
    "evidence_quality": (
        3.0,
        "How solid is the news basis for believing any of this?",
        "primary sources, filings, official data, multiple independent outlets",
        "one blog post or a single vendor's press release",
    ),
}

PLAN_THRESHOLD = 80.0


@dataclass
class OpportunityScore:
    title: str
    thesis: str
    trigger: str                       # the news or observation that raised it
    scores: dict[str, float]           # rubric key -> 0..10
    notes: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        missing = set(RUBRIC) - set(self.scores)
        if missing:
            raise ValueError(
                f"every rubric item must be scored, missing: {sorted(missing)}. "
                "A skipped criterion is a silent 10, which is how weak ideas pass."
            )
        for k, v in self.scores.items():
            if not 0 <= v <= 10:
                raise ValueError(f"{k}={v} out of range 0..10")

    @property
    def total(self) -> float:
        return round(sum(self.scores[k] / 10.0 * RUBRIC[k][0] for k in RUBRIC), 1)

    @property
    def deserves_plan(self) -> bool:
        return self.total >= PLAN_THRESHOLD

    @property
    def weakest(self) -> list[tuple[str, float]]:
        """Lowest weighted contributions — where the idea actually fails."""
        loss = {k: (10 - self.scores[k]) / 10.0 * RUBRIC[k][0] for k in RUBRIC}
        return sorted(loss.items(), key=lambda kv: -kv[1])[:3]

    def brief(self) -> str:
        """One-liner for anything below the plan threshold."""
        gaps = ", ".join(f"{k.replace('_', ' ')}" for k, _ in self.weakest[:2])
        return (f"[{self.total:.0f}] {self.title} — {self.thesis[:90]}\n"
                f"      held back by: {gaps}")

    def scorecard(self) -> str:
        lines = [f"{self.title}  —  score {self.total:.1f}/100",
                 f"  thesis: {self.thesis}",
                 f"  trigger: {self.trigger}", ""]
        for k, (w, _question, _, _) in RUBRIC.items():
            s = self.scores[k]
            bar = "█" * int(round(s)) + "·" * (10 - int(round(s)))
            lines.append(f"  {k:<22} {bar} {s:>4.1f}/10  (weight {w:>4.1f})")
            if k in self.notes:
                lines.append(f"      {self.notes[k]}")
        lines.append("")
        lines.append("  biggest gaps: " + ", ".join(
            f"{k} (-{v:.1f} pts)" for k, v in self.weakest))
        return "\n".join(lines)


def build_plan(op: OpportunityScore, operator_context: str = "") -> str:
    """Full plan for an opportunity that cleared the threshold.

    Structured around what kills small ventures rather than what makes a deck
    look good: no TAM slide, because a large market has never been the reason a
    small business survived. First customer, unit economics and cash conversion
    are the sections that matter.
    """
    if not op.deserves_plan:
        raise ValueError(
            f"{op.title} scored {op.total:.1f}, below {PLAN_THRESHOLD}. "
            "Writing a full plan for it would make a weak idea look considered."
        )

    w = op.weakest
    ctx = operator_context or "solo operator, Delhi, limited capital"
    return textwrap.dedent(f"""\
        # {op.title}

        **Score {op.total:.1f}/100** · generated {op.created_at:%Y-%m-%d}
        Operator context: {ctx}

        ## 1. The opportunity
        {op.thesis}

        **What triggered this:** {op.trigger}

        ## 2. Who pays, and why now
        Name the first three buyers. Not segments — organisations or people you
        could contact this week. If you cannot name three, the opportunity is not
        yet real and this plan is premature.

        - Buyer 1: ______________  budget holder: ______  reachable via: ______
        - Buyer 2: ______________  budget holder: ______  reachable via: ______
        - Buyer 3: ______________  budget holder: ______  reachable via: ______

        The "why now" must come from the trigger above. If the same plan would
        have worked two years ago, you have no timing advantage and are competing
        purely on execution.

        ## 3. The offer
        One sentence a buyer would repeat to their boss. Then:
        - What exactly is delivered
        - In what timeframe
        - At what price
        - What the buyer does today instead, and what that costs them

        Price from the cost of their current alternative, not from your hours.

        ## 4. First 60 days
        | Week | Action | Done when |
        |---|---|---|
        | 1 | 20 conversations with potential buyers. No selling, only listening. | 20 logged |
        | 2 | Write the offer from what you heard. One page. | Page exists |
        | 3-4 | Take the offer to 15 of those 20. | 15 pitched |
        | 5-6 | Deliver for the first paying customer, even at a discount. | Money received |
        | 7-8 | Write down what broke. Fix the offer. | v2 written |

        The goal of the first 60 days is one paying customer, not a product.

        ## 5. Unit economics
        Fill these in before spending anything:
        - Revenue per customer: ______
        - Direct cost to deliver: ______
        - Gross margin: ______
        - Hours per delivery: ______  -> effective hourly: ______
        - Cost to acquire one customer: ______
        - Payback period: ______

        **Kill criterion:** if acquisition cost exceeds gross margin on the first
        sale and there is no repeat purchase, stop. That is not a business.

        ## 6. Cash conversion
        Small ventures die solvent-on-paper and out of cash. Track:
        - Days from work done to invoice sent
        - Days from invoice to payment
        - Cash needed to cover that gap at 3 concurrent customers

        Ask for 50% upfront on the first engagement. If the buyer refuses, that
        is information about how much they want it.

        ## 7. Skills required
        - Have now: ______
        - Learn in under 90 days: ______
        - Must hire or partner for: ______

        Anything in the third bucket that is core to delivery is a serious risk
        for a solo operator. Consider narrowing the offer until it disappears.

        ## 8. The three things most likely to kill this
        {chr(10).join(f'        {i+1}. **{k.replace("_", " ").title()}** — currently costing {v:.1f} points. {RUBRIC[k][1]}' for i, (k, v) in enumerate(w))}

        For each, write the cheapest test that would tell you within two weeks
        whether it is fatal. Run those tests before anything else in this plan.

        ## 9. Regulatory and jurisdiction check
        Registration, GST, sector licences, and — if any revenue or supplier is
        cross-border — FEMA, LRS limits and TCS on remittance. Verify current
        rules with a qualified professional; this section is a prompt to check,
        not advice.

        ## 10. The pitch, in six lines
        1. **Problem:** who is losing what, today
        2. **Why now:** {op.trigger}
        3. **Offer:** what you deliver, in one sentence
        4. **Proof:** the first customer, or the 20 conversations
        5. **Economics:** price, margin, payback
        6. **Ask:** what you want from the listener, specifically

        ## Sources
        {chr(10).join(f'        - {s}' for s in op.sources) if op.sources else '        - none recorded — this plan rests on an unverified trigger'}

        ---
        *The score is a structured judgment against a fixed rubric, not an
        empirical probability. There is no population of comparable ventures to
        calibrate against. Its value is consistency: the same nine questions,
        asked of every idea, so the exciting ones do not get an easier ride.*
        """)


def render_digest(scored: list[OpportunityScore], operator_context: str = "") -> str:
    """Full plans above the threshold, one-liners below it."""
    if not scored:
        return "No business opportunities identified in this window."
    strong = [o for o in scored if o.deserves_plan]
    weak = sorted([o for o in scored if not o.deserves_plan],
                  key=lambda o: -o.total)

    parts = [f"Business opportunities — {datetime.now(timezone.utc):%Y-%m-%d}",
             f"{len(strong)} above {PLAN_THRESHOLD:.0f}, {len(weak)} below.", ""]
    for op in strong:
        parts += [op.scorecard(), "", build_plan(op, operator_context), ""]
    if weak:
        parts.append(f"--- Below {PLAN_THRESHOLD:.0f} (noted, not developed) ---")
        parts += [op.brief() for op in weak]
    return "\n".join(parts)


# =====================================================================
# Gap discovery — finding opportunities rather than reacting to headlines
# =====================================================================
"""
Scoring an idea someone hands you is the easy half. The harder half is
generating candidates, and it is a different activity: you are looking for a
mismatch between what people are trying to buy and what is being offered.

Each gap type below names the mismatch, where the signal shows up, and — the
part usually skipped — what would confirm it is real rather than apparent.
Almost every apparent gap is one of three things: already served by someone you
have not found, too small to sustain anyone, or structurally blocked for a
reason that is not visible from outside. The confirmation step is what separates
those from a genuine opening.

A note on the examples you raised. Import arbitrage and dropshipping are real
businesses and can produce income, but they score near zero on `durability`,
because the entry barrier is "found a supplier". That is only 5 of 100 points
here, which is deliberate: a low-durability business is a **job that pays**, not
an asset that compounds. Fine if that is what you want — but expect margins to
compress as others find the same supplier, and plan the next one before this one
decays.
"""

GAP_TYPES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "unserved_segment": (
        "A buyer group exists that current providers ignore because it is too "
        "small, too unglamorous, or priced wrong for them.",
        ("enterprise vendors quoting minimums a smaller buyer cannot meet",
         "forum and subreddit posts asking 'is there anything cheaper than X'",
         "procurement tenders repeatedly cancelled for lack of qualified bidders",
         "trade association complaints about supplier availability"),
        ("find three named buyers in that segment and ask what they use today",
         "confirm they have a budget line, not just a complaint",
         "check whether an incumbent already serves them under a name you missed"),
    ),
    "supply_chain_shift": (
        "A trade rule, tariff, sanction or logistics change makes a route "
        "newly viable or newly broken.",
        ("tariff notifications and customs circulars",
         "port and freight rate movements",
         "importers publicly seeking alternate sourcing",
         "sudden category price moves without a demand story"),
        ("verify the rule is in force, not proposed",
         "price the full landed cost including duty, freight and compliance",
         "confirm at least two suppliers exist so you are not a single point of failure"),
    ),
    "regulatory_trigger": (
        "A new compliance requirement creates mandatory demand on a deadline.",
        ("regulator circulars with effective dates",
         "new clauses appearing in standard contracts and tenders",
         "professional bodies announcing certification requirements"),
        ("confirm the deadline and who exactly it binds",
         "check whether existing providers have already staffed for it",
         "confirm you can legally deliver the work — some of it is licensed"),
    ),
    "capability_gap": (
        "Demand for a skill has outrun the number of people who have it.",
        ("job postings open for months at rising salaries",
         "agencies quoting long lead times",
         "training providers with waitlists"),
        ("confirm the skill can be acquired in under 90 days",
         "check whether the demand is for the skill or for a credential",
         "verify buyers will hire an individual, not only a firm"),
    ),
    "distribution_gap": (
        "A product exists and is wanted, but nobody is putting it in front of "
        "the people who want it in their language, region or channel.",
        ("marketplace searches with high volume and thin local results",
         "products with strong reviews but no regional presence",
         "communities repeatedly asking where to buy something"),
        ("confirm you can secure supply or an exclusive",
         "check whether the original seller plans to enter directly",
         "verify the margin survives shipping, returns and payment costs"),
    ),
    "service_around_a_product": (
        "A product is widely bought and badly implemented, supported or "
        "maintained. The service is the business, not the product.",
        ("support forums full of unresolved setup questions",
         "high-adoption tools with low completion or churn signals",
         "consultancies charging enterprise rates for routine work"),
        ("confirm buyers pay for help, rather than muddling through",
         "check whether the vendor gives it away free",
         "find out what the current alternative costs them"),
    ),
    "price_umbrella": (
        "Incumbents hold prices high because they all have the same cost base, "
        "and a different cost base undercuts them profitably.",
        ("uniform pricing across nominally competing providers",
         "long-standing providers with no pricing pressure",
         "buyers describing a category as 'expensive but no choice'"),
        ("confirm your cost base genuinely differs — not just thinner margin",
         "check for a regulatory or certification moat holding the price up",
         "model what happens when an incumbent matches your price for a quarter"),
    ),
}


def gap_brief(gap_type: str) -> str:
    if gap_type not in GAP_TYPES:
        raise ValueError(f"unknown gap type: {gap_type}. Known: {sorted(GAP_TYPES)}")
    desc, signals, confirms = GAP_TYPES[gap_type]
    lines = [f"{gap_type.replace('_', ' ').upper()}", f"  {desc}", "  where the signal shows up:"]
    lines += [f"    - {s}" for s in signals]
    lines.append("  what would confirm it is real:")
    lines += [f"    - {c}" for c in confirms]
    return "\n".join(lines)


def discovery_checklist() -> str:
    """All gap types, for scanning against a week of news and forum reading."""
    return "\n\n".join(gap_brief(g) for g in GAP_TYPES)


def durability_warning(op: "OpportunityScore") -> str | None:
    """Flag income-shaped ideas so they are not mistaken for asset-shaped ones."""
    if op.scores.get("durability", 10) <= 3:
        return ("Low durability: the entry barrier is small, so margins will compress "
                "as others arrive. This is a job that pays, not an asset that "
                "compounds. Viable for income — plan the next one while this one works.")
    return None
