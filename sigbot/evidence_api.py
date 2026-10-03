"""Evidence / status API — the single state surface both the marketing site and
the private dashboard consume.

Resolves the drift problem: database says BACKTEST -> API says BACKTEST ->
website says BACKTEST, with no place for a developer to relabel it. The frontend
NEVER calculates, reinterprets, or relabels — it renders finished facts. This
module is the serving layer; it reads the canonical store and the live system
status and produces the exact payloads a frontend displays.

TWO REFINEMENTS FROM THE BLUEPRINT:

  1. APPEND-ONLY EVIDENCE HISTORY. The store answered "what is the current figure?"
     This adds "what did SIGBOT believe at every point, and what evidence changed
     it?" — an EvidenceHistory that keeps every version of every fact, so a figure
     moving BACKTEST -> PAPER -> LIVE leaves a permanent audit trail.

  2. HONEST CAPABILITY REPORTING. The API does not claim the system is "live" or
     "deployment-verified". It reports exactly what evidence exists (and the
     explicit absence of LIVE facts), so the public claim can never outrun the
     evidence behind it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .canonical_evidence import (
    CanonicalEvidenceStore, EvidenceFact, EvidenceState, build_canonical_store)


# ── append-only evidence history (refinement 1) ─────────────────────────────
@dataclass
class EvidenceHistory:
    """Every version of every fact, in order. A fact is never overwritten here —
    a new measurement appends a new entry, so the full provenance timeline is
    preserved. This is the audit layer the current-value store is not."""
    _log: list[tuple[str, EvidenceFact]] = field(default_factory=list)
    _seq: int = 0

    def append(self, fact: EvidenceFact) -> str:
        """Record a fact version. Returns its immutable history id."""
        self._seq += 1
        hid = f"FACT-{self._seq:04d}"
        self._log.append((hid, fact))
        return hid

    def history_of(self, key: str) -> list[tuple[str, EvidenceFact]]:
        """Every recorded version of one figure, oldest first."""
        return [(hid, f) for hid, f in self._log if f.key == key]

    def current(self, key: str) -> EvidenceFact | None:
        """The latest recorded version of a figure."""
        versions = self.history_of(key)
        return versions[-1][1] if versions else None

    def all_entries(self) -> list[tuple[str, EvidenceFact]]:
        return list(self._log)

    def state_timeline(self, key: str) -> list[str]:
        """How a figure's evidence state evolved — e.g.
        ['backtest', 'paper', 'live']. The product's 'what did we know when'."""
        return [f.state.value for _, f in self.history_of(key)]


def build_history_from_store(store: CanonicalEvidenceStore) -> EvidenceHistory:
    """Seed the append-only history from the current canonical store. Future
    forward measurements append to it rather than overwriting."""
    h = EvidenceHistory()
    for key in store.all_keys():
        h.append(store.require(key))
    return h


# ── API payloads (what a frontend receives — finished, never recalculated) ──
@dataclass(frozen=True)
class FactPayload:
    """One figure as the API serves it. The frontend renders these fields as-is;
    it has no value, state, or label logic of its own."""
    key: str
    value: str
    evidence_state: str
    label: str                         # pre-rendered display label
    source: str
    as_of: str
    caveat: str


def fact_payload(f: EvidenceFact) -> FactPayload:
    return FactPayload(
        key=f.key, value=f.value, evidence_state=f.state.value,
        label=f.label(), source=f.source_finding, as_of=f.as_of,
        caveat=f.caveat)


@dataclass(frozen=True)
class EvidenceApiResponse:
    """The /evidence endpoint payload. Finished facts + an explicit, honest
    summary of what evidence states actually exist."""
    facts: tuple[FactPayload, ...]
    state_counts: dict[str, int]
    has_live: bool
    has_paper: bool
    honest_note: str


@dataclass(frozen=True)
class StatusApiResponse:
    """The /status endpoint payload. System health + capital authorization,
    generated from real state — never hand-set."""
    pipeline: dict[str, str]           # layer -> OK|FAIL|CAVEAT|RUNNING
    capital_authorization: str         # ALLOWED | BLOCKED
    safe_to_operate: bool


class EvidenceAPI:
    """The single serving layer. Both marketing and dashboard call these methods;
    neither does its own calculation. The API is read-only over finished state."""

    def __init__(self, store: CanonicalEvidenceStore | None = None,
                 history: EvidenceHistory | None = None) -> None:
        self.store = store or build_canonical_store()
        self.history = history or build_history_from_store(self.store)

    def get_fact(self, key: str) -> FactPayload:
        """Serve one figure. Raises if untraceable (via the store) — so the API
        cannot emit a number that isn't in the canonical evidence set."""
        return fact_payload(self.store.require(key))

    def evidence(self) -> EvidenceApiResponse:
        facts = tuple(fact_payload(self.store.require(k))
                      for k in self.store.all_keys())
        counts = {st.value: len(self.store.facts_by_state(st))
                  for st in EvidenceState}
        has_live = self.store.has_any_live()
        has_paper = bool(self.store.facts_by_state(EvidenceState.PAPER))
        if has_live:
            note = "Live performance figures exist and are labelled LIVE."
        elif has_paper:
            note = ("Forward paper figures exist (labelled PAPER). No live "
                    "capital figures yet — capital remains locked.")
        else:
            note = ("No forward (PAPER/LIVE) figures yet. All public figures are "
                    "historical (BACKTEST/OOS) or provisional. The forward record "
                    "is accumulating; capital remains locked.")
        return EvidenceApiResponse(facts, counts, has_live, has_paper, note)

    def status(self, pipeline: dict[str, str], safe: bool) -> StatusApiResponse:
        """Serve system status. capital is ALLOWED only if safe AND no pipeline
        layer failed — the API enforces fail-closed, the frontend just shows it."""
        any_fail = any(v == "FAIL" for v in pipeline.values())
        cap = "ALLOWED" if (safe and not any_fail) else "BLOCKED"
        return StatusApiResponse(pipeline=dict(pipeline),
                                 capital_authorization=cap,
                                 safe_to_operate=safe and not any_fail)

    def record_forward_fact(self, fact: EvidenceFact) -> str:
        """The ONLY way a forward (paper/live) figure enters: a real measurement
        is registered in the store (which blocks relabeling) AND appended to the
        immutable history. Returns the history id."""
        self.store.register(fact)       # enforces anti-laundering
        return self.history.append(fact)


def describe() -> str:
    api = EvidenceAPI()
    ev = api.evidence()
    return "\n".join([
        "EVIDENCE / STATUS API — one state surface for marketing + dashboard",
        "",
        "  database says BACKTEST -> API says BACKTEST -> website says BACKTEST.",
        "  The frontend renders finished facts; it never recalculates or relabels.",
        "",
        f"  Serving {len(ev.facts)} canonical facts. State counts: " +
        ", ".join(f"{k}={v}" for k, v in ev.state_counts.items() if v),
        "",
        "  APPEND-ONLY HISTORY: every version of every figure is kept, so the",
        "  audit layer answers 'what did SIGBOT believe when, and what evidence",
        "  changed it' — not just 'what is the current number'.",
        "",
        "  HONEST REPORTING: " + ev.honest_note,
        "",
        "  A forward figure enters ONLY via record_forward_fact (store enforces",
        "  anti-laundering; history keeps the permanent trail). Capital is",
        "  ALLOWED only when safe AND no pipeline layer failed — fail-closed.",
    ])
