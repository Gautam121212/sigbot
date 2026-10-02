"""Strategy Research & Innovation Engine — discover, dissect, ablate, invent,
validate, remember. Innovation unlimited; promotion brutally limited.

Replaces the narrow Strategy Distillation concept with the larger loop:
  Discover -> Dissect -> Ablate -> Learn -> Invent -> Recombine -> Validate ->
  Remember.
The existing engines (reality, scenario, harness, arena) remain underneath it.

THE LOAD-BEARING RULE, ENFORCED IN CODE (not merely intended):
  "Innovation can be unlimited; promotion must be brutally limited" is only true
  if the promotion gate's multiple-testing correction is sized to the TOTAL
  number of hypotheses GENERATED — every ablation and recombination the engine
  tried, not just the handful that reached OOS. The real family-wise error
  depends on the full research tree, not its visible leaves. So the engine COUNTS
  every hypothesis it generates and the promotion gate corrects against that
  running total. An innovation engine that forgets how many ideas it had is an
  overfitting machine that feels disciplined.

  The invention engine may generate as many ideas as it wants. It is NEVER
  allowed to decide which are true — a Hypothesis cannot become validated except
  through promote(), which applies the total-count-corrected bar.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from enum import Enum


# ── atoms: the components a strategy dissects into ──────────────────────────
class ComponentRole(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    SIZING = "sizing"
    FILTER = "filter"
    EXECUTION = "execution"


@dataclass(frozen=True)
class Component:
    """One atom extracted from a strategy — a capability, not a strategy."""
    name: str                          # e.g. "volume_shock", "20d_breakout"
    role: ComponentRole


# ── invention methods (how new hypotheses are generated) ────────────────────
class InventionMethod(str, Enum):
    DISSECTION = "dissection"           # pulled from an existing strategy
    ABLATION = "ablation"              # a strategy minus one component
    RECOMBINATION = "recombination"    # components from unrelated strategies
    TRANSFORMATION = "transformation"  # new variable from existing (accel-of-accel)
    INTERACTION = "interaction"        # feature A x feature B


@dataclass(frozen=True)
class Hypothesis:
    """A generated candidate. NEVER self-validating — it carries no truth value,
    only an id, its components, and how it was invented."""
    hypothesis_id: str
    components: tuple[Component, ...]
    method: InventionMethod


# ── the innovation counter — the spine of the whole thing ───────────────────
@dataclass
class InnovationLedger:
    """Counts EVERY hypothesis generated, and records component-level evidence
    and failure modes. The total count is what the promotion gate corrects
    against — this is the anti-overfitting spine."""
    _generated: int = 0
    _hypotheses: list[Hypothesis] = field(default_factory=list)
    _component_evidence: dict[str, list[float]] = field(default_factory=dict)
    _failure_modes: dict[str, str] = field(default_factory=dict)

    def record_generated(self, h: Hypothesis) -> None:
        """Every generated hypothesis is counted — including ones never tested.
        The count is permanent; it cannot be reset to make the bar easier."""
        self._generated += 1
        self._hypotheses.append(h)

    def total_generated(self) -> int:
        return self._generated

    def record_component_result(self, component: str, edge: float) -> None:
        self._component_evidence.setdefault(component, []).append(edge)

    def record_failure_mode(self, component: str, lesson: str) -> None:
        """Failure learning: not 'RSI failed' but WHY — e.g. 'no incremental
        value in these scenarios' or 'works but fails on capacity'."""
        self._failure_modes[component] = lesson

    def component_track_record(self, component: str) -> dict[str, float]:
        ev = self._component_evidence.get(component, [])
        if not ev:
            return {"n": 0}
        return {"n": len(ev), "mean_edge": round(sum(ev) / len(ev), 3),
                "times_positive": sum(1 for e in ev if e > 0)}

    def failure_lesson(self, component: str) -> str | None:
        return self._failure_modes.get(component)


# ── the permissive first gate (open it up, don't demand a great Sharpe) ─────
@dataclass(frozen=True)
class IntegrityScreen:
    """The deliberately permissive first gate: catch broken/unexecutable/leaky
    candidates, but let a weak-but-real signal through to be dissected. It does
    NOT require a strong Sharpe — a +2.5% edge is not killed here."""
    has_lookahead: bool
    sample_size: int
    cost_sensitivity_catastrophic: bool
    behaves_randomly: bool

    def passes(self) -> bool:
        return (not self.has_lookahead and self.sample_size >= 30
                and not self.cost_sensitivity_catastrophic
                and not self.behaves_randomly)


# ── promotion: the brutally limited gate ────────────────────────────────────
class PromotionVerdict(str, Enum):
    PROMOTED = "promoted"
    REJECTED_CORRECTION = "rejected — fails total-count-corrected bar"
    REJECTED_OOS = "rejected — no OOS edge"
    REJECTED_REDUNDANT = "rejected — redundant with existing capability"


def corrected_t_bar(total_generated: int) -> float:
    """The significance bar, sized to the TOTAL hypotheses generated across the
    whole research tree — not the number that happened to reach OOS. This is the
    enforcement of 'promotion brutally limited': the more the engine invented,
    the higher the bar every survivor must clear."""
    n = max(1, total_generated)
    alpha = 0.05 / n
    return round(statistics.NormalDist().inv_cdf(1 - alpha / 2), 3)


@dataclass
class PromotionGate:
    """Promotes a hypothesis to a validated capability ONLY if it clears the
    total-count-corrected OOS bar and isn't redundant. The innovation engine
    cannot bypass this — it is the only path from Hypothesis to validated."""
    innovation: InnovationLedger

    def promote(self, hypothesis: Hypothesis, oos_edge: float, oos_mean: float,
                oos_std: float, oos_n: int,
                correlation_with_library: float) -> PromotionVerdict:
        if oos_edge <= 0:
            return PromotionVerdict.REJECTED_OOS
        t = (oos_mean / (oos_std / math.sqrt(oos_n))) if oos_std > 0 and oos_n > 1 else 0.0
        bar = corrected_t_bar(self.innovation.total_generated())
        if t < bar:
            return PromotionVerdict.REJECTED_CORRECTION
        if correlation_with_library >= 0.5:
            return PromotionVerdict.REJECTED_REDUNDANT
        return PromotionVerdict.PROMOTED


@dataclass
class ValidatedLibrary:
    """The tiny, hard-won set of capabilities that cleared promotion."""
    _caps: list[str] = field(default_factory=list)

    def add(self, capability: str) -> None:
        self._caps.append(capability)

    def all(self) -> tuple[str, ...]:
        return tuple(self._caps)

    def promotion_rate(self, total_generated: int) -> float:
        if total_generated == 0:
            return 0.0
        return round(len(self._caps) / total_generated, 4)


def describe() -> str:
    return "\n".join([
        "RESEARCH & INNOVATION ENGINE — discover, dissect, ablate, invent,",
        "validate, remember.",
        "",
        "  Replaces the narrow distillation concept with the full loop. Strategies",
        "  dissect into COMPONENTS (atoms); ablation finds which matter; the",
        "  innovation engine recombines/transforms/crosses them into new",
        "  hypotheses it could never have found in one repo.",
        "",
        "  THE SPINE, ENFORCED IN CODE: the InnovationLedger counts EVERY",
        "  hypothesis generated — including untested ones — and the promotion",
        "  gate's significance bar is sized to that TOTAL, not to the few that",
        "  reached OOS. Invent 1000 ideas and every survivor must clear a bar set",
        "  for 1000 comparisons. Innovation is unlimited; promotion is brutal.",
        "",
        "  A Hypothesis is never self-validating — the only path to the validated",
        "  library is promote(), which applies the corrected bar + redundancy",
        "  check. The engine generates ideas; it never decides which are true.",
        "  Failure learning records WHY a component failed, not just that it did.",
    ])
