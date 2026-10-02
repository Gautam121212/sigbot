"""System assurance — does the WHOLE machine work, and can an experiment ever
reach real money? The layer that makes the two-brain architecture safe.

1,600+ unit tests prove components work in isolation. They do NOT prove the
end-to-end product works, and they do NOT prove the research brain can't leak
into production. This layer checks both — continuously — and treats the
production-lock as the one guarantee that must be structurally impossible to
violate.

THE CATASTROPHIC FAILURE MODE (why this is built first): a 24/7 research brain
generating thousands of hypotheses next to a live brain trading real money has
exactly one unrecoverable risk — an UNAPPROVED model reaching the trading path.
Every other risk is money lost to a validated-but-wrong strategy; this one is
money lost to a strategy that was never validated at all. So the core assertion
here is not "the pipeline is healthy" but "only the promoted champion can
authorize capital, and no research-generation model can, ever."

THE END-TO-END CHECKS (the plan's item 5): data arrived -> model consumed it ->
prediction recorded -> API has it -> website shows it -> values match ->
prediction came AFTER the data (no look-ahead) -> production runs the approved
version -> no experimental model on the trading path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ── the production lock: the one guarantee that cannot be violated ──────────
@dataclass(frozen=True)
class ApprovedChampion:
    """The ONLY model allowed to authorize capital. Its id is the lock."""
    model_id: str
    version: str
    promoted_at: str
    research_generation: str           # e.g. "gen-001"


class ModelOrigin(str, Enum):
    PRODUCTION = "production"           # the promoted champion
    RESEARCH = "research"              # a research-brain candidate — NEVER trades
    SHADOW = "shadow"                 # challenger in shadow mode — NEVER trades


@dataclass(frozen=True)
class TradeAuthRequest:
    """A model asking to authorize capital. Only the champion may."""
    model_id: str
    origin: ModelOrigin
    research_generation: str


class ExperimentLeakError(Exception):
    """Raised when a non-production model attempts to reach the trading path.
    This is the error that must never happen silently."""


def authorize_capital(request: TradeAuthRequest,
                      champion: ApprovedChampion) -> bool:
    """The single chokepoint. Returns True ONLY for the approved champion.
    A research or shadow model attempting to trade raises — loudly, never
    silently denied, so a leak is a visible incident, not a quiet no-op."""
    if request.origin != ModelOrigin.PRODUCTION:
        raise ExperimentLeakError(
            f"model {request.model_id} (origin={request.origin.value}, "
            f"gen={request.research_generation}) attempted to authorize capital "
            "— only the production champion may trade. This is a containment "
            "breach of the research brain.")
    if request.model_id != champion.model_id or \
            request.research_generation != champion.research_generation:
        raise ExperimentLeakError(
            f"model {request.model_id}/{request.research_generation} is not the "
            f"approved champion ({champion.model_id}/"
            f"{champion.research_generation}) — refusing capital authorization.")
    return True


# ── end-to-end pipeline checks (item 5) ─────────────────────────────────────
class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class PipelineCheck:
    name: str
    status: CheckStatus
    detail: str = ""


@dataclass
class EndToEndAssurance:
    """Walks the full path data -> model -> record -> api -> website and verifies
    each handoff. Any FAIL means the product is not trustworthy end-to-end even
    if every unit test passes."""

    def check_data_arrived(self, expected_filing: str,
                           arrived: bool) -> PipelineCheck:
        return PipelineCheck("data_arrived",
                             CheckStatus.PASS if arrived else CheckStatus.FAIL,
                             expected_filing)

    def check_model_consumed(self, data_id: str,
                             consumed_ids: set[str]) -> PipelineCheck:
        ok = data_id in consumed_ids
        return PipelineCheck("model_consumed_data",
                             CheckStatus.PASS if ok else CheckStatus.FAIL,
                             f"{data_id} {'in' if ok else 'NOT in'} consumed set")

    def check_prediction_recorded(self, pred_id: str,
                                  recorded_ids: set[str]) -> PipelineCheck:
        ok = pred_id in recorded_ids
        return PipelineCheck("prediction_recorded",
                             CheckStatus.PASS if ok else CheckStatus.FAIL, pred_id)

    def check_api_has_prediction(self, pred_id: str,
                                 api_ids: set[str]) -> PipelineCheck:
        ok = pred_id in api_ids
        return PipelineCheck("api_has_prediction",
                             CheckStatus.PASS if ok else CheckStatus.FAIL, pred_id)

    def check_website_matches_db(self, db_value: float,
                                 website_value: float) -> PipelineCheck:
        ok = abs(db_value - website_value) < 1e-9
        return PipelineCheck("website_matches_db",
                             CheckStatus.PASS if ok else CheckStatus.FAIL,
                             f"db={db_value} site={website_value}")

    def check_no_lookahead(self, data_available: datetime,
                           prediction_made: datetime) -> PipelineCheck:
        """The prediction must come AFTER the data it used became available."""
        ok = prediction_made >= data_available
        return PipelineCheck("prediction_after_data",
                             CheckStatus.PASS if ok else CheckStatus.FAIL,
                             f"data@{data_available.isoformat()} "
                             f"pred@{prediction_made.isoformat()}")

    def check_production_locked(self, running_id: str, running_gen: str,
                                champion: ApprovedChampion) -> PipelineCheck:
        ok = (running_id == champion.model_id
              and running_gen == champion.research_generation)
        return PipelineCheck("production_locked",
                             CheckStatus.PASS if ok else CheckStatus.FAIL,
                             f"running {running_id}/{running_gen} vs champion "
                             f"{champion.model_id}/{champion.research_generation}")


@dataclass
class AssuranceReport:
    checks: list[PipelineCheck] = field(default_factory=list)

    def add(self, c: PipelineCheck) -> None:
        self.checks.append(c)

    def all_pass(self) -> bool:
        return all(c.status == CheckStatus.PASS for c in self.checks)

    def failures(self) -> list[PipelineCheck]:
        return [c for c in self.checks if c.status == CheckStatus.FAIL]

    def product_trustworthy(self) -> bool:
        """The product is trustworthy end-to-end ONLY if every check passes.
        One failed handoff breaks the chain, however many unit tests pass."""
        return self.all_pass() and bool(self.checks)


def describe() -> str:
    return "\n".join([
        "SYSTEM ASSURANCE — does the WHOLE machine work, and can an experiment",
        "reach real money?",
        "",
        "  Built FIRST of the 24/7 vision, because the one unrecoverable risk of",
        "  a research brain running next to a live brain is an UNAPPROVED model",
        "  reaching the trading path. authorize_capital() is the single",
        "  chokepoint: only the promoted champion may authorize capital; a",
        "  research or shadow model attempting to trade RAISES ExperimentLeakError",
        "  — a visible incident, never a silent denial.",
        "",
        "  END-TO-END CHECKS (item 5): data arrived -> model consumed it ->",
        "  prediction recorded -> API has it -> website matches DB -> prediction",
        "  came AFTER the data -> production still runs the approved version. One",
        "  failed handoff means the product is not trustworthy end-to-end, however",
        "  many unit tests pass.",
        "",
        "  1,600+ green unit tests prove components work in isolation. This proves",
        "  the machine works as a whole — and that the research brain is contained.",
    ])
