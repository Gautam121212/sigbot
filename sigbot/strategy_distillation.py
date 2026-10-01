"""Strategy distillation engine — extract the capability, not the code.

The missing layer between the Arena (compare whole strategies) and the Scenario
Engine (where edge exists). It takes an external strategy as a RESEARCH INPUT,
asks "what capability does this contain and where does it actually work?",
separates that capability from the strategy's flaws, and routes a reconstructed
candidate through the shipped machinery (scenario engine + reality engine +
one-fix harness + OOS + multiple-testing correction).

Builds only on shipped components. No copied repo code. No new alpha asserted —
only alpha MEASURED after the flaws are stripped.

THE LOAD-BEARING HONESTY: the architecture is tempting because it assumes GitHub
strategies CONTAIN extractable capabilities that become specialists once cleaned
up. This project's record says otherwise — 8 of 9 alpha hypotheses killed. A
public strategy's "capability" is usually (a) a known factor already arbitraged
thin, or (b) an artifact of the very flaws (unrealistic fills, small-cap
exposure) that are its weaknesses — so stripping the flaws strips the capability.

THEREFORE: NO_SPECIALIST is the DEFAULT, first-class output. A capability becomes
a validated specialist ONLY when its edge survives OOS + correction AFTER the
flaws are removed. The distiller's real value is determining — honestly — that a
claimed capability usually does NOT survive separation from its flaws, rather
than laundering arbitraged factors into "proprietary edge".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FlawType(str, Enum):
    """Why a strategy's backtest overstates — the reality-engine gap taxonomy."""
    UNREALISTIC_FILLS = "unrealistic_fills"
    SMALLCAP_EXPOSURE = "smallcap_exposure"
    FIXED_STOP = "fixed_stop"
    LATE_ENTRY = "late_entry_after_move"
    SURVIVORSHIP = "survivorship_universe"
    NO_LIQUIDITY_CAP = "no_liquidity_cap"


class DistillationVerdict(str, Enum):
    NO_SPECIALIST = "NO_SPECIALIST"          # the default — capability didn't survive
    VALIDATED_SPECIALIST = "VALIDATED_SPECIALIST"
    CAPABILITY_WAS_THE_FLAW = "capability_was_the_flaw"  # edge vanished with flaws
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class Capability:
    """The useful MECHANISM extracted from a strategy — not its code. A hypothesis
    about what the strategy is good at, to be tested, never assumed."""
    name: str                          # e.g. "volatility_expansion_breakout"
    mechanism: str                     # plain-language description
    dependencies: tuple[str, ...]      # price, volume, ATR, ...
    claimed_scenarios: tuple[str, ...] # where the repo claims it works


@dataclass(frozen=True)
class FlawInventory:
    """The strategy's weaknesses, as reality-engine gaps. Each is a candidate for
    a SINGLE isolated fix through the harness."""
    flaws: tuple[FlawType, ...]

    def as_fixes(self) -> tuple[FlawType, ...]:
        return self.flaws


@dataclass(frozen=True)
class DistillationResult:
    """The outcome of distilling one strategy. NO_SPECIALIST by default."""
    strategy_id: str
    capability: Capability
    flaws: FlawInventory
    # measured AFTER flaws are stripped, per scenario
    edge_before_fixes: float           # raw, with flaws (the repo-flattering number)
    edge_after_fixes: float            # the capability alone, flaws removed
    specialist_scenarios: tuple[str, ...]   # where it survived OOS+correction
    verdict: DistillationVerdict

    def capability_survived_flaw_removal(self) -> bool:
        """Did edge survive once the flaws were stripped? The key question."""
        return self.edge_after_fixes > 0 and bool(self.specialist_scenarios)


@dataclass
class StrategyDistiller:
    """Extracts a capability, inventories flaws, and determines — honestly —
    whether the capability survives separation from the flaws. Routes candidate
    fixes through the one-change harness; never bundles, never asserts edge."""

    def extract_capability(self, strategy_id: str, mechanism: str,
                           dependencies: tuple[str, ...],
                           claimed_scenarios: tuple[str, ...]) -> Capability:
        """Name the useful mechanism. This is a HYPOTHESIS about what the strategy
        does, derived from its documented behaviour — not a claim it works."""
        return Capability(f"{strategy_id}_capability", mechanism,
                          dependencies, claimed_scenarios)

    def inventory_flaws(self, flaws: tuple[FlawType, ...]) -> FlawInventory:
        return FlawInventory(flaws)

    def distill(self, strategy_id: str, capability: Capability,
                flaws: FlawInventory, edge_before: float, edge_after: float,
                surviving_scenarios: tuple[str, ...],
                min_scenarios: int = 1) -> DistillationResult:
        """Decide the verdict. NO_SPECIALIST unless the capability's edge survives
        flaw removal AND clears the scenario gates. If edge collapses when flaws
        are stripped, the 'capability' WAS the flaw."""
        if edge_before > 0 and edge_after <= 0:
            verdict = DistillationVerdict.CAPABILITY_WAS_THE_FLAW
        elif len(surviving_scenarios) < min_scenarios:
            verdict = DistillationVerdict.NO_SPECIALIST
        elif edge_after > 0:
            verdict = DistillationVerdict.VALIDATED_SPECIALIST
        else:
            verdict = DistillationVerdict.NO_SPECIALIST
        return DistillationResult(
            strategy_id=strategy_id, capability=capability, flaws=flaws,
            edge_before_fixes=round(edge_before, 2),
            edge_after_fixes=round(edge_after, 2),
            specialist_scenarios=surviving_scenarios, verdict=verdict)


# ── distillation ledger — keep every result, especially the failures ────────
@dataclass
class DistillationLedger:
    """Append-only. A distillation that found NO specialist is the MOST common and
    MOST valuable kind of record — it documents that a strategy's claimed edge did
    not survive honest separation from its flaws."""
    _results: list[DistillationResult] = field(default_factory=list)

    def append(self, r: DistillationResult) -> None:
        self._results.append(r)

    def all(self) -> tuple[DistillationResult, ...]:
        return tuple(self._results)

    def validated_specialists(self) -> tuple[DistillationResult, ...]:
        return tuple(r for r in self._results
                     if r.verdict == DistillationVerdict.VALIDATED_SPECIALIST)

    def capability_was_flaw(self) -> tuple[DistillationResult, ...]:
        return tuple(r for r in self._results
                     if r.verdict == DistillationVerdict.CAPABILITY_WAS_THE_FLAW)

    def no_specialist(self) -> tuple[DistillationResult, ...]:
        return tuple(r for r in self._results
                     if r.verdict == DistillationVerdict.NO_SPECIALIST)

    def survival_rate(self) -> float:
        """Fraction of distilled strategies that yielded a validated specialist.
        Expected to be LOW — that honesty is the point."""
        if not self._results:
            return 0.0
        return round(len(self.validated_specialists()) / len(self._results), 3)


def describe() -> str:
    return "\n".join([
        "STRATEGY DISTILLATION ENGINE — extract the capability, not the code",
        "",
        "  Takes an external strategy as research input, names its useful",
        "  MECHANISM (a hypothesis, not a claim), inventories its FLAWS as",
        "  reality-engine gaps, then determines whether the capability's edge",
        "  SURVIVES once the flaws are stripped — via the scenario engine,",
        "  reality engine, one-fix harness, OOS and multiple-testing correction.",
        "",
        "  NO_SPECIALIST IS THE DEFAULT, FIRST-CLASS OUTPUT. A public strategy's",
        "  'capability' is usually a thin arbitraged factor or an artifact of its",
        "  own flaws (unrealistic fills, small-cap exposure) — so stripping the",
        "  flaws strips the edge. When edge collapses with the flaws, the verdict",
        "  is CAPABILITY_WAS_THE_FLAW. A validated specialist is earned, rarely.",
        "",
        "  The distiller's value is honest determination, not manufacture: it uses",
        "  other models' strengths without trusting their claims — the reality",
        "  engine decides whether the capability actually exists.",
    ])
