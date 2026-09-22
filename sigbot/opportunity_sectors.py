"""The 20 opportunity sector cards — the top layer of the Opportunities model.

Opening Opportunities shows 20 industry cards. Each card is a SECTOR of
business opportunity (Real Estate, Manufacturing, Energy...), and opening one
shows the individual ventures inside it (specific theses: a factory here, a
property there), judged by the barbell asymmetry rules in ventures.py.

The card's own readiness is NOT a stock-market number (that was the wrong
build). It is: how many live, worth-taking ventures this sector currently
holds, and how strong their combined asymmetry is. A sector with three
capped-downside, positive-EV ventures reads higher than one with none.
Risky ventures are counted and shown with the label, never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ventures import Venture

# The 20 industries, each a card. Ventures are assigned to a sector by keyword.
SECTORS: tuple[tuple[str, str], ...] = (
    ("Agriculture", "Crops, livestock, and raw food materials."),
    ("Mining", "Extraction of minerals, oil, gas, and geological materials."),
    ("Construction", "Building and maintaining homes, offices, and infrastructure."),
    ("Manufacturing", "Turning raw materials into finished products at scale."),
    ("Healthcare", "Medical services, hospitals, pharmaceuticals, devices."),
    ("Education", "Schools, colleges, and digital learning."),
    ("Information Technology", "Software, hardware, and data networks."),
    ("Finance and Banking", "Money circulation, investments, loans, banking."),
    ("Insurance", "Risk-management and financial-protection policies."),
    ("Hospitality and Tourism", "Lodging, travel, and dining."),
    ("Entertainment and Media", "Film, music, games, sport, news."),
    ("Retail", "Selling finished goods to the public."),
    ("Transportation and Logistics", "Moving people and freight by air, rail, sea, road."),
    ("Telecommunications", "Phone, mobile, and fibre networks."),
    ("Real Estate", "Buying, leasing, and managing property."),
    ("Energy and Utilities", "Electricity, gas, water, and waste services."),
    ("Automotive", "Designing, building, and repairing vehicles."),
    ("Aerospace", "Aircraft, satellites, and spacecraft."),
    ("Food Processing and Beverage", "Packaged food and drink from agriculture."),
    ("Consulting and Professional Services", "Legal, accounting, marketing, management."),
)

# Keywords that route a venture's title/thesis to a sector.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Agriculture": ("crop", "livestock", "agri", "plantation", "dairy", "grain farm"),
    "Mining": ("mine", "mining", "ore", "extraction", "drilling", "quarry"),
    "Construction": ("construction", "build-out", "infrastructure", "housing development"),
    "Manufacturing": ("factory", "manufactur", "assembly", "production line", "tape", "fabrication"),
    "Healthcare": ("clinic", "hospital", "pharma", "medical", "health", "biotech"),
    "Education": ("school", "college", "edtech", "learning", "training", "university"),
    "Information Technology": ("software", "saas", "platform", "data centre", "data center", "app", "cloud"),
    "Finance and Banking": ("bank", "lending", "loan", "fintech", "payments", "microfinance"),
    "Insurance": ("insurance", "insurtech", "underwrit", "reinsurance"),
    "Hospitality and Tourism": ("hotel", "resort", "tourism", "hospitality", "restaurant", "travel"),
    "Entertainment and Media": ("studio", "media", "streaming", "gaming", "music", "film"),
    "Retail": ("retail", "store", "e-commerce", "ecommerce", "marketplace", "shop"),
    "Transportation and Logistics": ("logistics", "freight", "shipping", "warehouse", "fleet", "port"),
    "Telecommunications": ("telecom", "fibre", "fiber", "5g", "network", "spectrum"),
    "Real Estate": ("property", "real estate", "residential", "commercial building", "reit", "land"),
    "Energy and Utilities": ("energy", "solar", "wind", "power plant", "utility", "grid", "hydro"),
    "Automotive": ("automotive", "vehicle", "ev ", "car ", "auto parts"),
    "Aerospace": ("aerospace", "aircraft", "satellite", "spacecraft", "drone", "aviation"),
    "Food Processing and Beverage": ("beverage", "food processing", "packaged food", "brewery", "bottling"),
    "Consulting and Professional Services": ("consulting", "advisory", "legal", "accounting", "agency"),
}


@dataclass(frozen=True)
class SectorCard:
    sector: str
    blurb: str
    readiness: float                 # 0-100, from the ventures inside it
    ventures: tuple = field(default_factory=tuple)
    worth_taking: int = 0
    risky: int = 0

    @property
    def risky_label(self) -> bool:
        return self.risky > 0 and self.worth_taking == 0


def assign_sector(v: Venture) -> str:
    """Route a venture to a sector by keyword; 'Consulting...' is the catch-all."""
    text = f"{v.title} {v.thesis}".lower()
    for sector, words in _KEYWORDS.items():
        if any(w in text for w in words):
            return sector
    return "Consulting and Professional Services"


def _readiness(ventures) -> float:
    """From the ventures inside: rewards worth-taking, capped, positive-EV ones.

    Empty sector -> 0. Otherwise the average, over worth-taking ventures, of a
    0-100 score built from EV and capped-downside — so a card is only 'ready'
    when it actually holds actionable, survivable asymmetric bets.
    """
    takers = [v for v in ventures if v.worth_taking]
    if not takers:
        return 0.0
    scores = []
    for v in takers:
        ev = max(0.0, min(3.0, v.ev_multiple))          # 0-3x -> 0-100
        scores.append(100.0 * ev / 3.0)
    return round(sum(scores) / len(scores), 1)


def build_sector_cards(ventures) -> list[SectorCard]:
    """The 20 cards, always all 20 (empty ones included), sorted by readiness."""
    by_sector: dict[str, list] = {name: [] for name, _ in SECTORS}
    for v in ventures:
        by_sector[assign_sector(v)].append(v)
    cards = []
    for name, blurb in SECTORS:
        vs = by_sector[name]
        takers = [v for v in vs if v.worth_taking]
        risky = [v for v in vs if v.risky]
        cards.append(SectorCard(
            sector=name, blurb=blurb, readiness=_readiness(vs),
            ventures=tuple(vs), worth_taking=len(takers), risky=len(risky)))
    return sorted(cards, key=lambda c: -c.readiness)


def to_rows(cards) -> list[dict]:
    """The 20 cards as plain dicts for the store the page reads."""
    rows = []
    for c in cards:
        rows.append({
            "sector": c.sector, "blurb": c.blurb, "readiness": c.readiness,
            "worth_taking": c.worth_taking, "risky": c.risky,
            "risky_label": c.risky_label,
            "ventures": [{
                "title": v.title, "thesis": v.thesis,
                "verdict": v.verdict(), "ev": round(v.ev_multiple, 2),
                "upside": v.upside_multiple, "risky": v.risky,
                "reasons": list(v.risk_reasons()), "sources": list(v.sources),
            } for v in c.ventures],
        })
    return rows
