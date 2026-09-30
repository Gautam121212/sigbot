"""Scenario intelligence engine — recognize the situation, select a validated
strategy for it. NOT a generic predictor; a conditional, leakage-proof library.

Starts from EVENTS/SCENARIOS rather than strategies. Records every occurrence of
a scenario with its MAGNITUDE (not just yes/no), attaches point-in-time forward
outcomes, and — via the shipped Strategy Arena — learns which strategies have a
conditional EDGE within each scenario. Inflection becomes the first proven
specialist inside this larger system, not something replaced.

TWO LEAKS THIS IS BUILT TO PREVENT (the caveat is the whole ballgame):

  LEAK 1 — FEATURE LOOK-AHEAD. A scenario recorded at date T uses ONLY data known
    at T. A ScenarioOccurrence seals its features with an as_of date and has no
    outcome field; outcomes are a SEPARATE later attachment (same pattern as
    paper_trading).

  LEAK 2 — OUTCOME-CONDITIONED SCENARIO DEFINITION (the subtle, dangerous one).
    If a scenario is DEFINED or refined by looking at which definitions had good
    forward outcomes, its measured edge is guaranteed to look real and guaranteed
    to be fiction — multiple testing in a scenario costume. DEFENSE: the set of
    ScenarioDefinitions is FROZEN (hashed) before the library measures a single
    forward return. You cannot add or refine a definition after seeing outcomes.

So: definitions are declared and frozen up front; occurrences are sealed
point-in-time; outcomes attach later; conditional edge is measured by the Arena
per scenario. Adaptation is gated (one-change harness), never reactive to a few
trades.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


# ── magnitude-carrying scenario feature ─────────────────────────────────────
@dataclass(frozen=True)
class Feature:
    """A scenario feature with its MAGNITUDE, not a yes/no flag. '+23% revenue
    acceleration' is a different scenario from '+2%'."""
    name: str
    value: float                       # the magnitude
    unit: str = ""


# ── a scenario DEFINITION — frozen before any outcome is measured ───────────
@dataclass(frozen=True)
class ScenarioDefinition:
    """What COUNTS as this scenario, in terms of feature thresholds. Declared and
    frozen BEFORE the library measures forward returns — this is the anti-leak-2
    control. The definition_hash is tamper-evidence."""
    scenario_id: str
    feature_bounds: tuple[tuple[str, float, float], ...]  # (name, min, max)

    def matches(self, features: dict[str, float]) -> bool:
        for name, lo, hi in self.feature_bounds:
            v = features.get(name)
            if v is None or not (lo <= v <= hi):
                return False
        return True

    def match_fraction(self, features: dict[str, float]) -> float:
        """How much of the definition the current features satisfy (for the
        'current company matches 87% of scenario' use case)."""
        if not self.feature_bounds:
            return 0.0
        hits = sum(1 for name, lo, hi in self.feature_bounds
                   if features.get(name) is not None
                   and lo <= features[name] <= hi)
        return round(hits / len(self.feature_bounds), 3)


class DefinitionsFrozenError(Exception):
    """Raised when a scenario definition is added/changed after outcomes exist."""


class ScenarioRegistry:
    """Holds the frozen set of scenario definitions. Once frozen (which happens
    before ANY outcome is measured), no definition can be added or changed —
    that is the structural defense against outcome-conditioned definitions."""

    def __init__(self) -> None:
        self._defs: dict[str, ScenarioDefinition] = {}
        self._frozen = False
        self._frozen_hash = ""

    def add(self, d: ScenarioDefinition) -> None:
        if self._frozen:
            raise DefinitionsFrozenError(
                f"cannot add scenario {d.scenario_id}: definitions were frozen "
                "before outcomes were measured (anti-leak-2). Adding a scenario "
                "after seeing outcomes is outcome-conditioned definition.")
        self._defs[d.scenario_id] = d

    def freeze(self) -> str:
        """Freeze the definition set. Called ONCE, before outcome measurement."""
        self._frozen = True
        payload = {sid: [list(b) for b in d.feature_bounds]
                   for sid, d in sorted(self._defs.items())}
        self._frozen_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        return self._frozen_hash

    def is_frozen(self) -> bool:
        return self._frozen

    def classify(self, features: dict[str, float]) -> list[str]:
        """Which frozen scenarios this feature set belongs to."""
        return [sid for sid, d in self._defs.items() if d.matches(features)]

    def definition(self, scenario_id: str) -> ScenarioDefinition | None:
        return self._defs.get(scenario_id)

    def all_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._defs))


# ── a sealed occurrence: features known at as_of, NO outcome ────────────────
@dataclass(frozen=True)
class ScenarioOccurrence:
    """One historical occurrence, sealed point-in-time. Has NO outcome field — a
    future price cannot reach into it (anti-leak-1)."""
    occurrence_id: str
    as_of: str
    symbol: str
    scenario_ids: tuple[str, ...]      # which frozen scenarios it matched
    features: tuple[Feature, ...]


@dataclass(frozen=True)
class ScenarioOutcome:
    """Attached LATER, separately, when forward prices are known. References the
    occurrence; never mutates it."""
    occurrence_id: str
    resolved_on: str
    ret_5d: float
    ret_20d: float
    ret_63d: float
    ret_126d: float


# ── the library ─────────────────────────────────────────────────────────────
@dataclass
class ScenarioLibrary:
    """Occurrences + their later outcomes, under a FROZEN registry. Measures the
    conditional distribution of outcomes per scenario — but only after freeze."""
    registry: ScenarioRegistry = field(default_factory=ScenarioRegistry)
    _occ: dict[str, ScenarioOccurrence] = field(default_factory=dict)
    _out: dict[str, ScenarioOutcome] = field(default_factory=dict)

    def record_occurrence(self, occ: ScenarioOccurrence) -> None:
        self._occ[occ.occurrence_id] = occ

    def attach_outcome(self, out: ScenarioOutcome) -> None:
        """Attaching an outcome requires the registry to be frozen — you cannot
        measure forward returns while definitions are still mutable."""
        if not self.registry.is_frozen():
            raise DefinitionsFrozenError(
                "registry must be frozen before outcomes are attached — "
                "measuring outcomes with mutable definitions enables leak 2")
        self._out[out.occurrence_id] = out

    def scenario_outcomes(self, scenario_id: str,
                          horizon: str = "ret_63d") -> list[float]:
        """The forward-return distribution for a scenario — the conditional
        'what normally happens when this occurs'."""
        rets: list[float] = []
        for oid, occ in self._occ.items():
            if scenario_id in occ.scenario_ids and oid in self._out:
                rets.append(getattr(self._out[oid], horizon))
        return rets

    def scenario_summary(self, scenario_id: str,
                         horizon: str = "ret_63d") -> dict[str, float]:
        rets = self.scenario_outcomes(scenario_id, horizon)
        n = len(rets)
        if n == 0:
            return {"n": 0}
        srt = sorted(rets)
        mean = sum(rets) / n
        median = srt[n // 2]
        wins = sum(1 for r in rets if r > 0)
        return {
            "n": n,
            "mean_pct": round(mean, 2),
            "median_pct": round(median, 2),
            "win_rate": round(wins / n * 100, 1),
            # tail-dependence flag (mean >> median) reused from the Ideas lesson
            "tail_dependent": 1.0 if (mean > 0 and median <= 0) else 0.0,
        }


def describe() -> str:
    return "\n".join([
        "SCENARIO INTELLIGENCE ENGINE — recognize the situation, pick a",
        "validated specialist for it.",
        "",
        "  Starts from EVENTS not strategies. Records each occurrence with its",
        "  MAGNITUDE (not yes/no), attaches point-in-time forward outcomes, and",
        "  learns via the Arena which strategies have a conditional EDGE within",
        "  each scenario. Inflection is the first proven specialist inside it.",
        "",
        "  TWO LEAKS PREVENTED STRUCTURALLY:",
        "    1. Feature look-ahead — occurrences seal features at as_of with NO",
        "       outcome field; outcomes attach separately later.",
        "    2. Outcome-conditioned definition (the subtle killer) — the set of",
        "       scenario definitions is FROZEN (hashed) before any outcome is",
        "       measured. You cannot add/refine a scenario after seeing which",
        "       definitions had good outcomes. Attaching an outcome to an",
        "       unfrozen registry raises.",
        "",
        "  Adaptation stays gated (one-change harness), never reactive to a few",
        "  trades. The Arena is a component inside this, not the main brain.",
    ])
