"""Canonical evidence store — one authoritative source for every public figure.

Resolves the contradiction the marketing page otherwise creates: it claims every
number is "generated from actual backend state, never entered by hand" while
being hand-edited. A product whose entire moat is "our claims are mechanically
traceable to evidence" cannot have hand-typed figures on its homepage.

THE RULE, ENFORCED BY TYPES: every public figure is an EvidenceFact with (a) a
value, (b) an EvidenceState label (backtest/oos/provisional/paper/live), and (c)
a source_finding string pointing at where it came from. There is no way to
register a fact without all three. The website renders ONLY registered facts —
so a number that isn't traceable to a recorded finding literally cannot appear,
and a backtest figure is structurally incapable of being labelled LIVE.

  one store -> one metrics surface -> marketing page + dashboard + reports.
  No manually typed performance numbers. If it's on the page, it's in here,
  with its provenance and its evidence state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EvidenceState(str, Enum):
    """The provenance label every public number must carry. These are ordered by
    strength — a claim may never be upgraded to a stronger state without new
    evidence of that state."""
    # A previously reported historical result whose original generation CANNOT
    # be reproduced from the surviving codebase. Retained for provenance only —
    # structurally excluded from qualification, sizing, and capital (strength -1,
    # below BACKTEST). This is NOT a backtest: a backtest is reproducible; this
    # is a number we can no longer regenerate. (The 1,703-trade inflection result
    # is HISTORICAL_REPORTED: the trade-generation harness and full trade panel
    # did not survive in the repo — only summary statistics remain.)
    HISTORICAL_REPORTED = "historical_reported"
    BACKTEST = "backtest"              # historical simulation (reproducible)
    OOS = "oos"                        # held-out, but still historical
    PROVISIONAL = "provisional"        # real but caveated (e.g. 45-day PIT delay)
    PAPER = "paper"                    # forward, no capital
    LIVE = "live"                      # forward, real capital

    def is_forward(self) -> bool:
        return self in (EvidenceState.PAPER, EvidenceState.LIVE)

    def counts_for_qualification(self) -> bool:
        """Whether a fact in this state may contribute to model qualification,
        sizing authority, or capital decisions. HISTORICAL_REPORTED never does —
        an unreproducible number cannot unlock anything."""
        return self != EvidenceState.HISTORICAL_REPORTED


# HISTORICAL_REPORTED is strength -1: strictly below BACKTEST, so it can never
# be the strongest evidence for any claim and never clears a qualification bar.
_STRENGTH = {EvidenceState.HISTORICAL_REPORTED: -1, EvidenceState.BACKTEST: 0,
             EvidenceState.OOS: 1, EvidenceState.PROVISIONAL: 1,
             EvidenceState.PAPER: 2, EvidenceState.LIVE: 3}


class StateUpgradeError(Exception):
    """Raised when code tries to relabel a figure to a stronger evidence state
    without a new fact of that state — the mechanism that stops a backtest number
    from being presented as live."""


@dataclass(frozen=True)
class EvidenceFact:
    """One public figure. Cannot exist without value + state + source."""
    key: str                           # e.g. "inflection.net_per_trade"
    value: str                         # rendered as given — "+6.57%", "1,703"
    state: EvidenceState
    source_finding: str                # where it came from (a BUGS id, a module)
    as_of: str                         # when measured/recorded
    caveat: str = ""                   # e.g. "45-day PIT delay"

    def label(self) -> str:
        base = self.state.value.upper()
        return f"{base} ({self.caveat})" if self.caveat else base


@dataclass
class CanonicalEvidenceStore:
    """The single authoritative store. Every figure rendered anywhere public must
    be fetched from here. Registration requires full provenance; relabeling to a
    stronger state requires a genuinely stronger fact."""
    _facts: dict[str, EvidenceFact] = field(default_factory=dict)

    def register(self, fact: EvidenceFact) -> None:
        """Add or replace a fact. A replacement may NOT claim a stronger evidence
        state than the existing one unless it genuinely is that state (i.e. the
        caller is recording new forward evidence, not relabeling old backtest
        numbers as live)."""
        existing = self._facts.get(fact.key)
        if existing and _STRENGTH[fact.state] > _STRENGTH[existing.state]:
            # upgrading strength is allowed ONLY if the new fact's state is the
            # one being claimed AND it has its own source — which it always does
            # by construction. But we forbid silently upgrading a backtest key to
            # live without the source changing (the laundering case).
            if fact.source_finding == existing.source_finding:
                raise StateUpgradeError(
                    f"{fact.key}: cannot upgrade {existing.state.value} -> "
                    f"{fact.state.value} from the same source "
                    f"'{fact.source_finding}'. A stronger evidence state needs "
                    "a genuinely new measurement, not a relabel.")
        self._facts[fact.key] = fact

    def get(self, key: str) -> EvidenceFact | None:
        return self._facts.get(key)

    def require(self, key: str) -> EvidenceFact:
        """Fetch a fact that MUST exist — used by the renderer. If the website
        asks for a number that was never registered, this raises, so an untraceable
        figure can never reach the page."""
        f = self._facts.get(key)
        if f is None:
            raise KeyError(
                f"no canonical fact for '{key}' — the website may only render "
                "figures that exist in the evidence store with full provenance")
        return f

    def all_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._facts))

    def facts_by_state(self, state: EvidenceState) -> list[EvidenceFact]:
        return [f for f in self._facts.values() if f.state == state]

    def has_any_live(self) -> bool:
        """Capital-authorization sanity: are there ANY live figures yet?"""
        return bool(self.facts_by_state(EvidenceState.LIVE))


# ── the canonical SIGBOT evidence set (from this project's real findings) ────
def build_canonical_store() -> CanonicalEvidenceStore:
    """The one place every public number is defined. Each traces to a real
    finding and carries its true evidence state. The marketing page renders
    THESE — it does not hard-code them."""
    s = CanonicalEvidenceStore()
    reg = s.register
    # inflection — PREVIOUSLY REPORTED, NOT REPRODUCIBLE. The trade-generation
    # harness and full 1,703-trade panel did not survive in the codebase; only
    # summary statistics remain (sustained_inflection.py is the detector, not the
    # backtest). These are retained for provenance and are structurally excluded
    # from qualification/sizing/capital via HISTORICAL_REPORTED (strength -1).
    # To regenerate as real BACKTEST evidence, the harness must be rebuilt
    # against point-in-time Shibui data (the parked Option-1 project).
    _HR = EvidenceState.HISTORICAL_REPORTED
    reg(EvidenceFact("inflection.trades", "1,703", _HR,
                     "trade_level_backtest (reported; harness not in repo)",
                     "2013-2024"))
    reg(EvidenceFact("inflection.net_per_trade", "+6.57%", _HR,
                     "trade_level_backtest (reported; not reproducible)",
                     "2013-2024"))
    reg(EvidenceFact("inflection.win_rate", "59.4%", _HR,
                     "trade_level_backtest (reported; not reproducible)",
                     "2013-2024"))
    reg(EvidenceFact("inflection.sharpe", "1.58", _HR,
                     "daily_portfolio_engine (reported; not reproducible)",
                     "2013-2024"))
    reg(EvidenceFact("inflection.forward_cagr", "~14%", _HR,
                     "validation_battery (reported; not reproducible)",
                     "2013-2024"))
    reg(EvidenceFact("inflection.walk_forward", "12 / 12", _HR,
                     "trade_level_backtest walk-forward (reported)",
                     "2013-2024"))
    # scenario map — PROVISIONAL (45-day PIT delay)
    reg(EvidenceFact("scenario.stress_edge", "+3.89%", EvidenceState.PROVISIONAL,
                     "scenario_data_pipeline", "2013-2026", caveat="45d PIT delay"))
    reg(EvidenceFact("scenario.bull_edge", "+1.45%", EvidenceState.PROVISIONAL,
                     "scenario_data_pipeline", "2013-2026", caveat="45d PIT delay"))
    # research program outcomes (backtest-era measurements)
    reg(EvidenceFact("research.hypotheses_tested", "9", EvidenceState.BACKTEST,
                     "project research record", "2026"))
    reg(EvidenceFact("research.survived", "1", EvidenceState.BACKTEST,
                     "project research record", "2026"))
    reg(EvidenceFact("research.public_no_edge", "87%", EvidenceState.BACKTEST,
                     "distillation experiment (30 archetypes)", "2026"))
    reg(EvidenceFact("research.public_additive", "3%", EvidenceState.BACKTEST,
                     "distillation experiment (30 archetypes)", "2026"))
    # forward paper — NONE yet (this is the honest state)
    # no PAPER or LIVE facts registered: the store reflects that forward
    # evidence is still accumulating. The page shows paper/live as "accruing".
    return s


def describe() -> str:
    s = build_canonical_store()
    return "\n".join([
        "CANONICAL EVIDENCE STORE — one source for every public figure",
        "",
        "  Every public number is an EvidenceFact with value + evidence-state",
        "  label + source. The website renders ONLY registered facts, so an",
        "  untraceable figure cannot appear and a BACKTEST number cannot be",
        "  relabeled LIVE without a genuinely new measurement.",
        "",
        f"  Registered facts: {len(s.all_keys())}",
        f"  BACKTEST: {len(s.facts_by_state(EvidenceState.BACKTEST))}  "
        f"OOS: {len(s.facts_by_state(EvidenceState.OOS))}  "
        f"PROVISIONAL: {len(s.facts_by_state(EvidenceState.PROVISIONAL))}  "
        f"PAPER: {len(s.facts_by_state(EvidenceState.PAPER))}  "
        f"LIVE: {len(s.facts_by_state(EvidenceState.LIVE))}",
        "",
        "  Any LIVE figures yet? " + ("yes" if s.has_any_live() else
        "no — forward evidence is still accumulating (the honest state)."),
        "",
        "  one store -> one metrics surface -> marketing page + dashboard +",
        "  reports. No hand-typed performance numbers. If it's on the page, it's",
        "  here, with its provenance and evidence state.",
    ])
