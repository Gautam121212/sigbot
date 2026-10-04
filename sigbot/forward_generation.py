"""Forward Generation — the immutable baseline that makes the freeze real.

The forward paper record is strong evidence ONLY if the system that produces it
is frozen. An accumulating record you keep tuning against is slow in-sample
fitting, not out-of-sample evidence. This module defines the frozen baseline so
that months from now the question "what did the system produce when we froze it?"
has an exact answer, not "what did it produce after we kept tweaking it?".

A ForwardGeneration captures the exact model/policy/config state at freeze time.
Every forward prediction belongs to a generation. A change to the strategy does
NOT edit the record — it opens a NEW generation with its own track. The old
record is immutable and keeps its generation id.

This is the operational form of the rule Rishi set: no tuning the model because
of the accumulating results. If a change is proposed, it is a new generation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ForwardGeneration:
    """An immutable freeze baseline. Everything that defines 'the strategy' is
    captured here; the frozen_hash seals it. Two generations with the same hash
    are the same frozen system."""
    generation_id: str              # e.g. "FWD-GEN-001"
    frozen_at: str                  # ISO timestamp
    git_commit: str
    model_versions: dict[str, str]  # family -> version
    trader_policy_version: str
    governor_policy_version: str
    risk_budget_rung: str           # the EvidenceRung name at freeze
    execution_assumptions: dict     # costs, slippage model, fill rules
    research_library_hash: str
    frozen_hash: str = ""

    @staticmethod
    def create(generation_id: str, git_commit: str,
               model_versions: dict[str, str], trader_policy_version: str,
               governor_policy_version: str, risk_budget_rung: str,
               execution_assumptions: dict, research_library_hash: str
               ) -> "ForwardGeneration":
        frozen_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps({
            "git_commit": git_commit, "model_versions": model_versions,
            "trader_policy_version": trader_policy_version,
            "governor_policy_version": governor_policy_version,
            "risk_budget_rung": risk_budget_rung,
            "execution_assumptions": execution_assumptions,
            "research_library_hash": research_library_hash}, sort_keys=True)
        return ForwardGeneration(
            generation_id=generation_id, frozen_at=frozen_at,
            git_commit=git_commit, model_versions=dict(model_versions),
            trader_policy_version=trader_policy_version,
            governor_policy_version=governor_policy_version,
            risk_budget_rung=risk_budget_rung,
            execution_assumptions=dict(execution_assumptions),
            research_library_hash=research_library_hash,
            frozen_hash=_hash(payload))

    def matches(self, git_commit: str, model_versions: dict[str, str],
                trader_policy_version: str, governor_policy_version: str,
                risk_budget_rung: str, execution_assumptions: dict,
                research_library_hash: str) -> bool:
        """Does the CURRENT system still match this frozen baseline? If not, the
        strategy has drifted and a new generation is required before the forward
        record can continue as clean evidence."""
        payload = json.dumps({
            "git_commit": git_commit, "model_versions": model_versions,
            "trader_policy_version": trader_policy_version,
            "governor_policy_version": governor_policy_version,
            "risk_budget_rung": risk_budget_rung,
            "execution_assumptions": execution_assumptions,
            "research_library_hash": research_library_hash}, sort_keys=True)
        return self.frozen_hash == _hash(payload)


class GenerationViolation(Exception):
    """Raised when a prediction is attributed to a generation whose frozen state
    no longer matches the running system — i.e. the strategy changed without a
    new generation being opened. Fail-closed: the record must stay clean."""


@dataclass
class GenerationRegistry:
    """Holds the generations. New generations are appended; existing ones are
    never edited. The 'active' generation is the newest one."""
    generations: list[ForwardGeneration] = field(default_factory=list)

    def open_generation(self, gen: ForwardGeneration) -> None:
        if any(g.generation_id == gen.generation_id for g in self.generations):
            raise ValueError(f"generation {gen.generation_id} already exists")
        self.generations.append(gen)

    def active(self) -> ForwardGeneration | None:
        return self.generations[-1] if self.generations else None

    def get(self, generation_id: str) -> ForwardGeneration | None:
        for g in self.generations:
            if g.generation_id == generation_id:
                return g
        return None

    def verify_current_matches_active(self, **current_state) -> None:
        """Before recording a forward prediction, confirm the running system
        still matches the active generation. If it drifted, raise — the operator
        must open a new generation rather than silently contaminating the record."""
        gen = self.active()
        if gen is None:
            raise GenerationViolation("no active forward generation")
        if not gen.matches(**current_state):
            raise GenerationViolation(
                f"running system no longer matches {gen.generation_id} — "
                "open a new generation before recording (do not edit the record)")


def describe() -> str:
    return "\n".join([
        "FORWARD GENERATION — the immutable baseline that makes the freeze real",
        "",
        "  The forward paper record is clean evidence ONLY if the system is",
        "  frozen. A ForwardGeneration seals the exact model/policy/config/commit",
        "  at freeze time (frozen_hash). Every forward prediction belongs to a",
        "  generation.",
        "",
        "  A strategy change does NOT edit the record — it opens a NEW generation",
        "  with its own track. The old record keeps its generation id, immutable.",
        "",
        "  verify_current_matches_active() checks, before recording, that the",
        "  running system still matches the frozen baseline. If it drifted, it",
        "  raises GenerationViolation (fail-closed) — the operator must open a new",
        "  generation, never silently contaminate the existing record.",
        "",
        "  This is the operational form of the freeze: no tuning the model",
        "  because of the accumulating results. A change is a new generation.",
    ])
