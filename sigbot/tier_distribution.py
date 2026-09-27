"""Tier distribution — proper per-model capital & trade allocation across tiers.

The audit found real problems:
  - the allocation used "core" but the tiers are "stable" (key mismatch bug).
  - crypto and ideas had very-risky bets but NO stable anchor (all lottery).
  - very-risky must hold the LEAST capital despite being where the big wins are —
    because most very-risky bets lose; you size them small and let winners run.

THE RULES (per model, capital-weighted):
  STABLE:     most capital (frequent, high-win, modest return) — the anchor.
  RISKY:      moderate capital.
  VERY-RISKY: LEAST capital (rare, low-win, huge-tail) — small bets, many shots.

Models WITHOUT a stable tier (crypto, ideas) get a synthetic anchor: they hold
more CASH in place of the missing stable sleeve, so a model with only lottery
bets is not fully deployed into lottery bets. This fixes the imbalance.
"""
from __future__ import annotations

from dataclasses import dataclass

# Capital weights within a model, by tier (must sum to <= 1; remainder = cash).
TIER_CAPITAL = {"stable": 0.60, "risky": 0.30, "very-risky": 0.10}

# Trade-frequency expectation by tier (relative) — stable trades often, very-
# risky rarely. Used to check distribution is sane.
TIER_FREQUENCY = {"stable": 1.0, "risky": 0.4, "very-risky": 0.15}


@dataclass(frozen=True)
class ModelDistribution:
    model: str
    weights: dict[str, float]
    cash: float
    note: str


def distribute(model: str, has_stable: bool, has_risky: bool,
               has_very_risky: bool) -> ModelDistribution:
    """Allocate capital across the tiers a model actually has. A missing tier's
    weight becomes CASH (esp. missing stable -> a cash anchor)."""
    w = {}
    cash = 0.0
    for tier, cap in TIER_CAPITAL.items():
        present = {"stable": has_stable, "risky": has_risky,
                   "very-risky": has_very_risky}[tier]
        if present:
            w[tier] = cap
        else:
            cash += cap                # missing tier -> held as cash
    note = (f"{model}: " + ", ".join(f"{t} {v:.0%}" for t, v in w.items())
            + (f", cash {cash:.0%}" if cash else ""))
    if not has_stable and has_very_risky:
        note += " (cash replaces the missing stable anchor — not all-lottery)"
    return ModelDistribution(model, w, round(cash, 2), note)


def check_very_risky_holds_least(dist: ModelDistribution) -> bool:
    """The key safety rule: very-risky must never hold more than stable/risky."""
    vr = dist.weights.get("very-risky", 0.0)
    return all(vr <= dist.weights.get(t, 0.0) or t not in dist.weights
               for t in ("stable", "risky"))


def describe() -> str:
    configs = {
        "stocks": (True, True, True), "news": (True, True, True),
        "ventures": (True, True, True), "crypto": (False, True, True),
        "ideas": (False, True, True),
    }
    lines = ["TIER DISTRIBUTION (per-model capital, very-risky holds least)", ""]
    for m, (s, r, v) in configs.items():
        d = distribute(m, s, r, v)
        ok = "OK" if check_very_risky_holds_least(d) else "VIOLATION"
        lines.append(f"  [{ok}] {d.note}")
    lines.append("")
    lines.append("Very-risky holds the LEAST capital everywhere (small bets, big")
    lines.append("tail). Crypto & ideas hold cash where they lack a stable tier,")
    lines.append("so a lottery-only model is not fully deployed into lottery bets.")
    return "\n".join(lines)
