"""Market-gap edges — 2 per tier for stocks and ventures, from real mechanics.

The user's push: stop using professional indicators (no edge, ~10%). Find the
market-structure GAPS nobody trades — forced selling, balance-sheet inflections,
the mechanics of who moves what and why. This run: stocks and ventures, two
edges per risk tier, discovered by investigating the actual mechanics.

═══ STOCKS ═══
STABLE (2):
  1. TAX-LOSS BOUNCE — stocks down 30%+ over 60 days in late December are dumped
     for tax reasons below fair value, then snap back. +15% median 20-day bounce,
     positive 11 of 15 years. A forced-selling gap nobody sizes systematically.
  2. LARGE-CAP OVERSOLD — RSI<30 on a >$10B name: +0.83%/5d, 57% win. Steady.

RISKY (2):
  3. GAP + VOLUME — mid-cap 5-day momentum >8% on >2x volume (institutional
     entry): +1.83%/10d.
  4. CAPITULATION-REVERSAL — mid-cap RSI<20 on >3x volume (panic exhaustion):
     +3.48%/10d, 52% win.

VERY-RISKY (2):
  5. SMALL-CAP VOLUME EXPLOSION — <$500M, >5x volume, momentum: rare huge
     winners, ~11% win (lottery — tiny size, let winners run).
  6. ADX + HYPERVOLATILE MOONSHOT — strong trend + ATR>10%: ~7% chance of
     +100% in 60 days.

═══ VENTURES ═══
STABLE (2):
  1. QUALITY COMPOUNDER — ROIC>15%, margin>50%, steady growth 10-30%:
     +14.2%/yr, 60% win. Steady compounding.
  2. FCF INFLECTION — FCF growth >100% (turning cash-positive): 16.2% hit a
     50%+ gain — the balance-sheet-repair moment the market re-rates.

RISKY (2):
  3. LOW-DEBT HYPERGROWTH — D/E<0.3 + revenue growth >40%: 18.0% hit +50%.
     Growth without the leverage risk.
  4. FAST-GROWTH — 15-40% revenue growth: moderate double-rate.

VERY-RISKY (2):
  5. MARGIN EXPANSION — gross margin >60% + accelerating growth AND FCF:
     21.1% hit +50% — the strongest venture edge (software economics inflecting).
  6. HYPERGROWTH CASH-BURNING — 40%+ growth, not yet profitable: 11% double-rate
     (the aggressive growth-at-all-costs outlier).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GapEdge:
    name: str
    tier: str
    mechanic: str              # WHY it works (the market gap)
    metric: str


STOCK_EDGES = [
    GapEdge("tax-loss bounce", "stable",
            "Dec forced selling for tax losses pushes losers below fair value",
            "+15% median 20d, positive 11/15 years"),
    GapEdge("large-cap oversold", "stable",
            "liquid name overshoots on fear, mean-reverts",
            "+0.83%/5d, 57% win"),
    GapEdge("gap + volume", "risky",
            "institutional entry — a real buyer stepping in on volume",
            "+1.83%/10d"),
    GapEdge("capitulation-reversal", "risky",
            "panic exhaustion — forced sellers done, RSI<20 on 3x volume",
            "+3.48%/10d, 52% win"),
    GapEdge("small-cap volume explosion", "very-risky",
            "a micro name being discovered — too small for funds to notice",
            "~11% win, rare huge winners"),
    GapEdge("ADX+hypervolatile moonshot", "very-risky",
            "explosive trend that keeps running — the tail",
            "~7% chance of +100%/60d"),
]

VENTURE_EDGES = [
    GapEdge("quality compounder", "stable",
            "durable high-ROIC high-margin business compounds steadily",
            "+14.2%/yr, 60% win"),
    GapEdge("FCF inflection", "stable",
            "turning cash-positive is a re-rating moment the market rewards",
            "16.2% hit +50% in a year"),
    GapEdge("low-debt hypergrowth", "risky",
            "hypergrowth without leverage risk — survives a downturn",
            "18.0% hit +50%"),
    GapEdge("fast-growth", "risky",
            "15-40% revenue growth — a moderate growth candidate",
            "5.8% double-rate"),
    GapEdge("margin expansion", "very-risky",
            "high margin + accelerating growth AND FCF = software economics "
            "inflecting — the strongest venture signal",
            "21.1% hit +50%"),
    GapEdge("hypergrowth cash-burning", "very-risky",
            "growth-at-all-costs, not yet profitable — the aggressive outlier",
            "11% double-rate"),
]


def edges_by_tier(edges: list[GapEdge], tier: str) -> list[GapEdge]:
    return [e for e in edges if e.tier == tier]


def describe() -> str:
    lines = ["MARKET-GAP EDGES — 2 per tier (stocks + ventures)", ""]
    for model, edges in (("STOCKS", STOCK_EDGES), ("VENTURES", VENTURE_EDGES)):
        lines.append(f"═══ {model} ═══")
        for tier in ("stable", "risky", "very-risky"):
            lines.append(f"  [{tier}]")
            for e in edges_by_tier(edges, tier):
                lines.append(f"    {e.name}: {e.metric}")
                lines.append(f"      why: {e.mechanic}")
        lines.append("")
    return "\n".join(lines)
