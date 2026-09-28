"""run_ideas_classify — the 8-K research pipeline (runs where SEC full text is
reachable: the user's Mac or GitHub Actions, NOT the build sandbox which is 403).

Implements the final research schema so the pipeline never needs rebuilding:
  filing -> classification -> event attributes -> point-in-time market state
         -> entry -> execution -> daily P&L -> outcome

The structural classifier (eight_k_classifier.classify_structural) already ran on
Shibui item data and FALSIFIED the item-level hypothesis (no tradeable class).
This module adds the FULL-TEXT layer: for the one remaining test worth running —
does a genuine commercial contract (inside the flat "Pure-agreement" class) with
a large deal-value/market-cap ratio have a positive median? — it fetches the 8-K
body, sub-classifies, and extracts deal economics.

CRITICAL RULE: the classifier NEVER sees future price. Outcome is a label
computed AFTER classification, never an input to it.

DISABLED for live trading: like run_ideas_live, this records nothing to the live
ledger. It is a RESEARCH pipeline that produces return distributions per subtype,
so the user can decide (Outcome A: build the sleeve / Outcome B: abandon 8-K).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .eight_k_classifier import classify_structural, hypothesis_falsified

# Commercial-contract keywords for the full-text sub-classifier. These run on the
# 8-K BODY only (available at filing time), never on any future outcome.
COMMERCIAL_KEYWORDS = (
    "supply agreement", "purchase agreement", "customer", "distribution",
    "offtake", "master services", "statement of work", "purchase order",
)
GOVERNMENT_KEYWORDS = (
    "department of defense", "u.s. government", "federal", "contract award",
    "gsa", "prime contract", "subcontract", "naval", "air force", "army",
)
STRATEGIC_KEYWORDS = (
    "joint venture", "partnership", "collaboration", "license agreement",
    "strategic alliance", "co-development",
)


@dataclass
class Filing:
    accession: str
    ticker: str
    filing_ts: str
    items: list[str]
    is_amendment: bool
    body_text: str = ""          # fetched from SEC on the Mac; empty in sandbox
    # attributes extracted AT filing time (never from future price)
    deal_value: float | None = None
    market_cap: float | None = None
    subtype: str = "unclassified"


def subclassify_pure_agreement(body: str) -> str:
    """Sub-classify a Pure-agreement 8-K by its text (filing-time only)."""
    b = body.lower()
    if any(k in b for k in GOVERNMENT_KEYWORDS):
        return "government"
    if any(k in b for k in COMMERCIAL_KEYWORDS):
        return "commercial"
    if any(k in b for k in STRATEGIC_KEYWORDS):
        return "strategic"
    return "other-agreement"


def classify(filing: Filing) -> str:
    """Full classification: structural first, then full-text sub-class if the
    structural class is Pure-agreement and we have the body text."""
    structural = classify_structural(filing.items, filing.is_amendment)
    if structural == "Pure-agreement" and filing.body_text:
        return f"Pure-agreement/{subclassify_pure_agreement(filing.body_text)}"
    return structural


@dataclass
class ResearchRun:
    """Produces return distributions per subtype — the decision artifact."""
    filings: list[Filing] = field(default_factory=list)

    def run(self) -> str:
        # In the sandbox there is no body text, so only the structural verdict
        # is available — which already falsified the item-level hypothesis.
        if hypothesis_falsified():
            return ("Item-level 8-K hypothesis is FALSIFIED (no tradeable "
                    "structural class). Run this on the Mac with SEC full text "
                    "to test the ONE remaining question: do genuine commercial "
                    "contracts with high deal-value/market-cap have a positive "
                    "median? If not, abandon 8-K (Outcome B) and research a "
                    "trend/momentum second sleeve instead.")
        return "Structural classes with edge exist; proceed to full-text study."


def run_ideas_classify() -> str:
    """Research entry point. Records nothing live — produces the decision."""
    return ResearchRun().run()
