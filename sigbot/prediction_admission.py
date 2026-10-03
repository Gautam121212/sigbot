"""Prediction admission — a scheduler wake-up is not a prediction.

The scheduler can fire 1,000 times; that must not mean 1,000 predictions. A
prediction is admitted to the record ONLY when it passes two hard invariants:

  1. TIMESTAMP VALIDITY (look-ahead guard). The information the prediction is
     based on must be known strictly BEFORE the outcome window opens:
         as_of  <=  prediction_created_at  <  outcome_start  <  outcome_end
     A prediction whose as_of is at or after outcome_start is REJECTED from the
     record — it cannot have predicted a move it could already see.

  2. MODEL-SPECIFIC DEDUP. "One active thesis per model + its natural key",
     NOT "one row every time the scanner wakes". The dedup key differs by model
     semantics so News can legitimately fire twice on two distinct events while
     Stocks cannot re-record an already-open symbol:
         stocks   -> model + symbol + horizon
         crypto   -> model + pair + horizon + signal_instance
         news     -> model + event_id + asset + horizon
         ventures -> thesis_id
         ideas    -> opportunity_id

This module decides ADMISSION only. It does not predict, schedule, or trade.
Existing predictions are immutable once their outcome window begins — a changed
view is a NEW prediction, never an edit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Model(str, Enum):
    STOCKS = "stocks"
    CRYPTO = "crypto"
    NEWS = "news"
    VENTURES = "ventures"
    IDEAS = "ideas"


class AdmissionVerdict(str, Enum):
    ADMIT = "admit"
    REJECT_LOOKAHEAD = "reject_lookahead"       # as_of not before outcome window
    REJECT_BAD_WINDOW = "reject_bad_window"     # outcome_start >= outcome_end etc.
    REJECT_DUPLICATE = "reject_duplicate"       # an open thesis already exists


@dataclass(frozen=True)
class PredictionClaim:
    """A candidate prediction the scheduler produced. Carries the full timestamp
    chain so admission can verify no look-ahead."""
    model: Model
    symbol: str
    as_of: datetime                 # timestamp of the information used
    created_at: datetime            # when the model made the call
    outcome_start: datetime         # when the outcome window opens
    outcome_end: datetime           # when it closes (resolution)
    # model-specific dedup components (unused ones stay empty)
    horizon: str = ""
    signal_instance: str = ""
    event_id: str = ""
    thesis_id: str = ""
    opportunity_id: str = ""

    def dedup_key(self) -> str:
        """The natural key for this model — what 'already have this' means here."""
        m = self.model
        if m == Model.STOCKS:
            return f"stocks|{self.symbol}|{self.horizon}"
        if m == Model.CRYPTO:
            return f"crypto|{self.symbol}|{self.horizon}|{self.signal_instance}"
        if m == Model.NEWS:
            return f"news|{self.event_id}|{self.symbol}|{self.horizon}"
        if m == Model.VENTURES:
            return f"ventures|{self.thesis_id}"
        if m == Model.IDEAS:
            return f"ideas|{self.opportunity_id}"
        return f"{m.value}|{self.symbol}"


@dataclass(frozen=True)
class AdmissionResult:
    verdict: AdmissionVerdict
    dedup_key: str
    reason: str

    def admitted(self) -> bool:
        return self.verdict == AdmissionVerdict.ADMIT


def _window_valid(c: PredictionClaim) -> bool:
    return c.outcome_start < c.outcome_end


def _no_lookahead(c: PredictionClaim) -> bool:
    """The core invariant: information must predate the outcome window, and the
    call must be made at or after the information, and before the window opens."""
    return (c.as_of <= c.created_at
            and c.created_at < c.outcome_start
            and c.as_of < c.outcome_start)


def admit(claim: PredictionClaim, open_keys: set[str]) -> AdmissionResult:
    """Decide whether this candidate becomes a recorded prediction. open_keys is
    the set of dedup keys for predictions currently OPEN (unresolved). Checks run
    in integrity order: window shape, then look-ahead, then dedup."""
    key = claim.dedup_key()
    if not _window_valid(claim):
        return AdmissionResult(AdmissionVerdict.REJECT_BAD_WINDOW, key,
                               "outcome_start must be before outcome_end")
    if not _no_lookahead(claim):
        return AdmissionResult(
            AdmissionVerdict.REJECT_LOOKAHEAD, key,
            f"look-ahead: as_of={claim.as_of.isoformat()} is not strictly "
            f"before outcome_start={claim.outcome_start.isoformat()} "
            "(the model could already see the move)")
    if key in open_keys:
        return AdmissionResult(
            AdmissionVerdict.REJECT_DUPLICATE, key,
            "an open prediction with this key already exists — "
            "a scheduler wake-up is not a new prediction")
    return AdmissionResult(AdmissionVerdict.ADMIT, key, "admitted")


# ── the full timestamp chain stored with every admitted prediction ──────────
@dataclass(frozen=True)
class PredictionTimestamps:
    """What every admitted prediction records, so the forward record is auditable
    and the look-ahead guarantee is permanent, not just checked once."""
    as_of: str
    prediction_created_at: str
    outcome_start: str
    outcome_end: str
    resolution_time: str = ""       # filled at resolution, empty while open

    @staticmethod
    def from_claim(c: PredictionClaim) -> "PredictionTimestamps":
        return PredictionTimestamps(
            as_of=c.as_of.isoformat(),
            prediction_created_at=c.created_at.isoformat(),
            outcome_start=c.outcome_start.isoformat(),
            outcome_end=c.outcome_end.isoformat())


def describe() -> str:
    return "\n".join([
        "PREDICTION ADMISSION — a scheduler wake-up is not a prediction",
        "",
        "  Two hard invariants gate every candidate before it enters the record:",
        "    1. Look-ahead guard — as_of <= created_at < outcome_start < outcome_end.",
        "       A prediction whose information isn't strictly before its outcome",
        "       window is REJECTED (it could already see the move).",
        "    2. Model-specific dedup — one active thesis per model's natural key",
        "       (stocks: symbol+horizon; news: event+asset+horizon; ventures:",
        "       thesis_id; ...), so News can fire twice on two events but Stocks",
        "       cannot re-record an open symbol.",
        "",
        "  Admission only — no predicting, scheduling or trading. Existing",
        "  predictions are immutable once their window opens; a changed view is a",
        "  NEW prediction, never an edit. Every admitted prediction stores the",
        "  full timestamp chain so the look-ahead guarantee is permanent.",
    ])
