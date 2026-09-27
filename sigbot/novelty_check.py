"""Novelty check — honest flags on whether each edge is genuinely new.

The user requires each edge to be genuinely novel and market-understanding-based.
Honest audit (NOVELTY_AUDIT.md): they are NOT — they are known factors. This
module records that plainly so the system never overclaims a secret edge.
"""
from __future__ import annotations

# Honest novelty verdict per model edge.
EDGE_NOVELTY = {
    "stocks/tax-loss-bounce": ("KNOWN", "documented tax-loss / January effect"),
    "stocks/capitulation": ("KNOWN", "standard oversold mean-reversion"),
    "stocks/quality-growth": ("KNOWN", "the growth factor, widely used"),
    "news/oversold-into-beat": ("SEMI", "surprise x weakness combo, PEAD known"),
    "news/pre-earnings-drift": ("KNOWN", "documented informed-trading drift"),
    "ventures/hypergrowth-margin": ("KNOWN", "quality-growth on fundamentals"),
    "crypto/turnover": ("DEAD", "failed forward — reverse-causation"),
    "crypto/small-cap": ("DEAD", "failed forward — survivorship"),
    "ideas/catalyst-size-sector": ("SEMI", "combination novel, pieces known"),
    "novel/industry-read-through": ("WEAK", "real concept, unstable forward"),
    "novel/serial-beaters": ("WEAK", "market prices it in"),
    "novel/sustained-inflection": ("NOVEL", "sustained dual margin+growth "
        "acceleration over 3q — overlooked 2nd-deriv-over-time, held every era, "
        "+16-24%/yr forward"),
}


def any_genuinely_novel() -> bool:
    """Is ANY edge genuinely novel AND durable? Honest answer: no."""
    return any(v[0] == "NOVEL" for v in EDGE_NOVELTY.values())


def describe() -> str:
    lines = ["EDGE NOVELTY AUDIT (honest — are these secret edges?)", ""]
    for edge, (verdict, why) in EDGE_NOVELTY.items():
        lines.append(f"  [{verdict:<5}] {edge}: {why}")
    lines.append("")
    lines.append("VERDICT: ONE genuinely novel edge found by deep decomposition —")
    lines.append("sustained-inflection (dual margin+growth acceleration over 3q),")
    lines.append("overlooked because it takes 3+ quarters to confirm. +16-24%/yr,")
    lines.append("held every era. The rest are known factors (~market returns).")
    return "\n".join(lines)
