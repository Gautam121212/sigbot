"""Bridge from news articles to scored business opportunities.

## Why a news scan cannot produce an 80

The proposed version mapped headlines to gap types and scored the full rubric
from them. Its arithmetic ceiling, computed across every gap type at maximum
source strength, is **66.1** — against a plan threshold of 80. The full-plan
branch could never fire. Briefs forever, silently.

That is not a calibration bug to be fixed by raising the numbers. It is the
rubric telling the truth. The two heaviest criteria are demand evidence (18) and
distribution (18), and **a headline cannot answer either**. No article tells you
whether you can reach a paying buyer in 60 days, or whether you have the skills.
Inflating those scores so the threshold is reachable would produce plans whose
confidence came from nowhere.

So the scan produces **candidates**, not verdicts. Each carries:

  - the rubric items a news article genuinely does speak to, scored
  - the items it cannot speak to, held at a neutral 5 and listed in
    `needs_enrichment`
  - a `ceiling`: the best score reachable if every unknown turned out perfect

You then answer three questions per candidate — can you name three buyers, can
you reach them, can you do the work — and `enrich()` recomputes. That is what
unlocks a plan. The last mile is human, and pretending otherwise is how you end
up with a beautifully formatted plan for a business you cannot sell.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .providers.news import dedupe, source_quality, tokens
from .types import Article
from .venture import GAP_TYPES, PLAN_THRESHOLD, RUBRIC, OpportunityScore

# Rubric items a news article cannot answer. Held neutral and surfaced, never guessed.
UNKNOWABLE_FROM_NEWS = ("distribution", "skill_fit", "demand_evidence")

_GAP_SIGNALS: dict[str, tuple[str, ...]] = {
    "unserved_segment": ("no provider", "unserved", "underserved", "waitlist", "backlog",
                         "cannot find", "no local", "turned away", "unmet demand"),
    "supply_chain_shift": ("tariff", "sanction", "supply chain", "freight rate", "port",
                           "import ban", "customs", "alternate sourcing", "export curb"),
    "regulatory_trigger": ("mandatory", "compliance deadline", "licence required",
                           "license required", "new rule", "certification required",
                           "must comply", "soc2", "iso 27001", "dpdp"),
    "capability_gap": ("talent gap", "skill shortage", "shortage of engineers",
                       "vacancies unfilled", "open for months", "hiring difficulty"),
    "distribution_gap": ("not available in", "no distributor", "local language",
                         "no regional presence", "where to buy", "does not ship"),
    "service_around_a_product": ("implementation partner", "setup help", "support backlog",
                                 "integration services", "poorly implemented",
                                 "consulting around"),
    "price_umbrella": ("overpriced", "no cheaper option", "uniform pricing",
                       "price gouging", "captive market"),
}

# Multi-word commodities must be matched as phrases: a \w+ capture reads
# "shortage of palm oil" as "palm" and silently drops the match.
CARRY_COMMODITIES = (
    "natural gas", "palm oil", "crude oil", "iron ore", "coking coal",
    "copper", "nickel", "lithium", "cobalt", "aluminium", "aluminum", "zinc",
    "wheat", "rice", "sugar", "urea", "uranium", "silver", "platinum",
)
_SUPPLY_WORDS = r"(shortage|deficit|surplus|glut|squeeze)"
_STORAGE_PATTERN = re.compile(
    rf"\b{_SUPPLY_WORDS}\s+(?:of|in)\s+({'|'.join(re.escape(c) for c in CARRY_COMMODITIES)})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RawVentureSignal:
    gap_type: str
    title: str
    thesis: str
    trigger: str
    sources: list[str]
    strength: float          # 0..1, from source quality and corroboration
    commodity: str | None = None


@dataclass
class NewsCandidate:
    """A scored candidate plus an honest account of what the news could not tell us."""

    opportunity: OpportunityScore
    gap_type: str
    needs_enrichment: list[str] = field(default_factory=list)
    commodity: str | None = None

    @property
    def score(self) -> float:
        return self.opportunity.total

    @property
    def ceiling(self) -> float:
        """Best achievable score if every unknown resolved perfectly."""
        s = dict(self.opportunity.scores)
        for k in self.needs_enrichment:
            s[k] = 10.0
        return round(sum(s[k] / 10.0 * RUBRIC[k][0] for k in RUBRIC), 1)

    @property
    def can_reach_plan(self) -> bool:
        return self.ceiling >= PLAN_THRESHOLD

    def render(self) -> str:
        op = self.opportunity
        lines = [
            f"[{self.score:.0f} now, up to {self.ceiling:.0f}] {op.title}",
            f"  gap type: {self.gap_type.replace('_', ' ')}",
            f"  thesis: {op.thesis}",
            f"  trigger: {op.trigger}",
        ]
        if self.commodity:
            lines.append(f"  commodity thesis on {self.commodity} — run the carry test "
                         "in reference_class before assuming storage is profitable")
        if self.needs_enrichment:
            lines.append("  the news cannot answer these; you must:")
            for k in self.needs_enrichment:
                lines.append(f"    - {k.replace('_', ' ')}: {RUBRIC[k][1]}")
        lines.append(f"  {'CAN' if self.can_reach_plan else 'CANNOT'} reach the "
                     f"{PLAN_THRESHOLD:.0f} plan threshold even if every unknown resolves well")
        if op.sources:
            lines.append("  sources: " + "; ".join(op.sources[:2]))
        return "\n".join(lines)


def enrich(candidate: NewsCandidate, **answers: float) -> OpportunityScore:
    """Recompute a candidate with your answers to the unknowable items.

        enrich(c, demand_evidence=8, distribution=7, skill_fit=6)

    Only items listed in `needs_enrichment` may be supplied — overriding what the
    news actually evidenced would discard the one part of the score that came
    from outside your own optimism.
    """
    invalid = set(answers) - set(candidate.needs_enrichment)
    if invalid:
        raise ValueError(
            f"{sorted(invalid)} were evidenced by the news and may not be overridden; "
            f"enrichable items are {candidate.needs_enrichment}"
        )
    scores = dict(candidate.opportunity.scores)
    notes = dict(candidate.opportunity.notes)
    for k, v in answers.items():
        if not 0 <= v <= 10:
            raise ValueError(f"{k}={v} out of range 0..10")
        scores[k] = float(v)
        notes[k] = "supplied by the operator, not derived from news"
    return OpportunityScore(
        title=candidate.opportunity.title, thesis=candidate.opportunity.thesis,
        trigger=candidate.opportunity.trigger, scores=scores, notes=notes,
        sources=candidate.opportunity.sources,
    )


class VentureNewsScanner:
    """Turn news into scored business-opportunity candidates."""

    def __init__(self, min_source_quality: float = 0.5):
        self.min_source_quality = min_source_quality

    def scan(self, articles: Sequence[Article]) -> list[NewsCandidate]:
        return [self._score(sig) for sig in self._extract(articles)]

    # ------------------------------------------------------------ extract
    def _extract(self, articles: Sequence[Article]) -> list[RawVentureSignal]:
        out: list[RawVentureSignal] = []
        for cluster in dedupe(articles):
            lead = cluster[0]
            # Quality comes from the BEST outlet in the cluster, not whichever
            # published first. If a weak blog breaks a story and Reuters then
            # confirms it, the evidence is Reuters-grade — taking the lead's
            # quality would discard the corroboration that matters most.
            q = max(source_quality(a.source) for a in cluster)
            if q < self.min_source_quality:
                continue
            text = f"{lead.title} {lead.summary}".lower()
            tok = tokens(text)
            srcs = [f"{a.source} ({a.published_at:%Y-%m-%d})" for a in cluster[:2]]
            corroboration = min(1.0, 0.6 + 0.12 * (len(cluster) - 1))

            commodity = supply_word = None
            m = _STORAGE_PATTERN.search(text)
            if m:
                supply_word = m.group(1).lower()
                commodity = m.group(2).lower()

            # One signal per cluster: the best-matching gap type. The proposed
            # version emitted a separate opportunity for every keyword family that
            # hit, so a single article could produce five near-identical alerts.
            best_gap, best_hits = None, 0
            for gap, keywords in _GAP_SIGNALS.items():
                hits = sum(1 for kw in keywords if kw in text)
                if hits > best_hits:
                    best_gap, best_hits = gap, hits
            if commodity and (best_gap is None or best_hits < 2):
                best_gap, best_hits = "supply_chain_shift", max(best_hits, 1)
            if best_gap is None or best_hits == 0:
                continue

            density = best_hits / max(len(tok), 1)
            title = (f"{commodity.title()} supply thesis" if commodity
                     else lead.title[:80])
            thesis = GAP_TYPES[best_gap][0]
            if commodity:
                # Read from the bound value, not from `m` — reaching back into the
                # match object leaves a crash waiting for the day the branches
                # stop lining up.
                thesis = (f"Reporting points to a {supply_word} in {commodity}. "
                          "Any storage version of this needs the carry test first.")
            out.append(RawVentureSignal(
                gap_type=best_gap, title=title, thesis=thesis, trigger=lead.title,
                sources=srcs, strength=min(1.0, q * corroboration + min(density, 0.2)),
                commodity=commodity,
            ))
        return out

    # -------------------------------------------------------------- score
    def _score(self, sig: RawVentureSignal) -> NewsCandidate:
        scores = {k: 5.0 for k in RUBRIC}
        notes: dict[str, str] = {}

        # Only what a news article can genuinely evidence gets moved.
        scores["evidence_quality"] = round(3.0 + 7.0 * sig.strength, 1)
        notes["evidence_quality"] = f"source quality and corroboration ({sig.strength:.2f})"

        if sig.gap_type in ("service_around_a_product", "capability_gap", "distribution_gap"):
            scores["time_to_first_revenue"] = 7.0
            notes["time_to_first_revenue"] = "service or resale models can invoice within weeks"
            scores["capital_required"] = 8.0
            notes["capital_required"] = "service-heavy; little inventory or licence cost"
        elif sig.gap_type == "supply_chain_shift":
            scores["time_to_first_revenue"] = 4.0
            notes["time_to_first_revenue"] = "sourcing and logistics setup runs one to three months"
            scores["capital_required"] = 3.0
            notes["capital_required"] = "working capital for inventory, freight and duty"

        if sig.gap_type in ("unserved_segment", "distribution_gap"):
            scores["competition_density"] = 7.0
            notes["competition_density"] = "the reported gap implies few incumbents in this slice"

        if sig.gap_type in ("regulatory_trigger", "supply_chain_shift"):
            scores["regulatory_friction"] = 4.0
            notes["regulatory_friction"] = "compliance or cross-border rules are part of the work"
            scores["durability"] = 3.0
            notes["durability"] = "time-bound: the edge expires when the rule or disruption normalises"
        elif sig.gap_type == "unserved_segment":
            scores["durability"] = 5.0
            notes["durability"] = "depends on building relationships before others arrive"

        for k in UNKNOWABLE_FROM_NEWS:
            notes[k] = "a news article cannot answer this — you must"

        return NewsCandidate(
            opportunity=OpportunityScore(
                title=sig.title, thesis=sig.thesis, trigger=sig.trigger,
                scores={k: float(max(0.0, min(10.0, v))) for k, v in scores.items()},
                notes=notes, sources=sig.sources,
            ),
            gap_type=sig.gap_type,
            needs_enrichment=list(UNKNOWABLE_FROM_NEWS),
            commodity=sig.commodity,
        )


def render_candidates(candidates: Sequence[NewsCandidate]) -> str:
    if not candidates:
        return "No business-opportunity candidates in this window."
    ranked = sorted(candidates, key=lambda c: -c.ceiling)
    lines = [f"{len(ranked)} business candidate(s) from news.",
             "Scores shown as 'now, up to ceiling'. No candidate reaches a plan on "
             "news alone — answer the listed questions, then call enrich().", ""]
    lines += [c.render() + "\n" for c in ranked]
    return "\n".join(lines)
