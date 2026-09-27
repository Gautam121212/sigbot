"""Tiered edges — each model earns at all three risk tiers, not just one.

The user's structure: every model should have edges for stable profit, for risky
trades, and for very-risky trades — and more than one per tier where they exist.
This maps each model's measured edges to the tier they belong to, so the account
can earn steadily from the stable tier and asymmetrically from the risky tiers.

The tiers (by market-cap / conviction, measured):
  STABLE      — large, liquid, high win-rate, modest return. The base.
  RISKY       — mid-cap / higher-turnover, bigger return, lower win-rate.
  VERY-RISKY  — small-cap / explosive, rare huge winners, mostly losers (lottery).

STOCKS (measured, US 2010-2026):
  stable:      large-cap oversold (RSI<30, cap>10B) — +0.83%/5d, 57% win
               + panic-capitulation (crisis years) + pullback-in-uptrend
  risky:       mid-cap volume turnover (>3x, cap 1-10B) — +2.6%/20d, 53% win
  very-risky:  small-cap volume explosion (>5x, cap<500M, momentum) — 11% win,
               rare huge winners + the ADX+hypervolatile moonshot

CRYPTO:
  stable:      (none — liquid majors have no direction edge; magnitude sizing)
  risky:       move-detection (volume+volatility precursors) — volatility bet
  very-risky:  small-cap turnover ($10-100M, >30% turnover) — +26% median 30d

NEWS:
  stable:      confirmed-surprise + pre-earnings drift (modest, steady)
  risky:       oversold-into-beat (+4.1%) — a beat on a beaten-down stock
  very-risky:  big-beat oversold (+5.45%) + the miss-overbought SHORT (-3.93%)

VENTURES:
  stable:      quality compounder (ROIC>15%, margin>50%, growth 10-30%) —
               +14.2%/yr, 60% win — steady compounding, the stable base
  risky:       fast-growth (15-40% rev growth) — moderate double-rate
  very-risky:  hypergrowth + high margin (9.4% double) / cash-burning (11%)

IDEAS:
  stable:      (none — opportunities are event-driven)
  risky:       material agreement on a mid-cap (8.3% big-move)
  very-risky:  health-care stacked catalyst on a mid-cap (~14% big-move)
"""
from __future__ import annotations

from dataclasses import dataclass, field

STABLE = "stable"
RISKY = "risky"
VERY_RISKY = "very-risky"


@dataclass(frozen=True)
class Edge:
    name: str
    tier: str
    metric: str                # the measured result
    win_rate: float | None = None


@dataclass
class ModelEdges:
    model: str
    edges: list[Edge] = field(default_factory=list)

    def by_tier(self, tier: str) -> list[Edge]:
        return [e for e in self.edges if e.tier == tier]

    def has_all_tiers(self) -> bool:
        tiers = {e.tier for e in self.edges}
        return {RISKY, VERY_RISKY} <= tiers   # every model has at least risky+


MODELS = {
    "stocks": ModelEdges("stocks", [
        Edge("large-cap oversold", STABLE, "+0.83%/5d", 0.57),
        Edge("panic-capitulation", STABLE, "+3-10%/trade in crisis years", 0.57),
        Edge("pullback-in-uptrend", STABLE, "positive 15/17 years", 0.55),
        Edge("mid-cap volume turnover", RISKY, "+2.6%/20d", 0.53),
        Edge("small-cap volume explosion", VERY_RISKY, "11% win, rare huge", 0.11),
        Edge("ADX+hypervolatile moonshot", VERY_RISKY, "7% chance of +100%/60d", None),
    ]),
    "crypto": ModelEdges("crypto", [
        Edge("magnitude sizing", RISKY, "regime-independent move-size", None),
        Edge("move-detection (vol+news)", RISKY, "2+ precursors = move imminent", None),
        Edge("small-cap turnover", VERY_RISKY, "+26% median 30d (validate fwd)", 0.87),
    ]),
    "news": ModelEdges("news", [
        Edge("confirmed-surprise", STABLE, "modest steady drift", None),
        Edge("pre-earnings drift", STABLE, "54-55% direction", 0.545),
        Edge("oversold-into-beat", RISKY, "+4.1%/5d", None),
        Edge("big-beat oversold", VERY_RISKY, "+5.45%/5d", None),
        Edge("miss-overbought short", VERY_RISKY, "-3.93%/5d (short)", None),
    ]),
    "ventures": ModelEdges("ventures", [
        Edge("quality compounder (ROIC>15%, margin>50%)", STABLE, "+14.2%/yr", 0.60),
        Edge("fast-growth (15-40%)", RISKY, "5.8% double-rate", None),
        Edge("hypergrowth+high-margin", VERY_RISKY, "9.4% double-rate", None),
        Edge("hypergrowth cash-burning", VERY_RISKY, "11% double-rate", None),
    ]),
    "ideas": ModelEdges("ideas", [
        Edge("material agreement mid-cap", RISKY, "8.3% big-move", None),
        Edge("health-care stacked catalyst", VERY_RISKY, "~14% big-move", None),
    ]),
}


def describe() -> str:
    lines = ["TIERED EDGES — every model earns at multiple risk tiers", ""]
    for model, me in MODELS.items():
        lines.append(f"### {model}")
        for tier in (STABLE, RISKY, VERY_RISKY):
            es = me.by_tier(tier)
            if es:
                for e in es:
                    w = f", {e.win_rate:.0%} win" if e.win_rate else ""
                    lines.append(f"  [{tier}] {e.name}: {e.metric}{w}")
            else:
                lines.append(f"  [{tier}] — (none; not this model's nature)")
        lines.append("")
    return "\n".join(lines)
