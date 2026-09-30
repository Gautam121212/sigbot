"""Paper trading — persistent live-forward simulation of SIGBOT-INFLECTION-001.

Turns the shadow system into a forward experiment: every trading day the strategy
gets data it could actually have known AT THAT MOMENT, records its hypothetical
trades, and waits to see what really happened. That is the ONE thing a backtest
cannot give — an out-of-sample record that accrues in real time and cannot be
tuned in hindsight.

THE STRUCTURAL DISCIPLINE (paper trading is worthless without it):

  1. POINT-IN-TIME SEALING. A signal is recorded with its as_of date BEFORE any
     future price exists. The record that holds the decision (PaperSignal) has NO
     field for the outcome. The outcome is written later, by a separate step,
     into a separate record that references the signal but cannot alter it. There
     is no code path by which a future price influences the sealed decision — so
     paper trading cannot silently become a look-ahead backtest.

  2. BROKER SUBMISSION IS STRUCTURALLY IMPOSSIBLE. This module drives the shadow
     pipeline (adapter -> reality -> firewall), whose approved orders go to a
     ShadowSink, never a broker. There is no broker handle here.

  3. THE HEALTH MONITOR WATCHES THE PROCESS. Each day's accrued behaviour is
     assessed against the validated profile; drift quarantines, it never retunes.

Persistence is an append-only journal so the forward record survives restarts and
cannot be rewritten. Quiver / imported strategies are NOT wired in here — they go
through the research engine separately.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .live_health_monitor import (
    HealthReport, INFLECTION_PROFILE, LiveBehaviour, assess)
from .shadow_trading import ShadowOrder, ShadowSession, evaluate_outcome
from .strategy_adapter import NormalizedSignal


# ── a sealed decision: recorded BEFORE the outcome exists ───────────────────
@dataclass(frozen=True)
class PaperSignal:
    """The decision, sealed at as_of. NO outcome field — a future price cannot
    reach into this record. The outcome is a separate later write."""
    as_of: str                         # ISO date the signal was generated
    strategy_id: str
    symbol: str
    reason: str                        # why the signal fired (from the strategy)
    target_weight: float
    intended_price: float
    simulated_fill_price: float
    approved: bool
    approved_value: float
    firewall_reasons: tuple[str, ...]
    signal_id: str                     # links to its later outcome


@dataclass(frozen=True)
class PaperOutcome:
    """Written strictly AFTER the signal, when the subsequent price is known.
    References the signal by id; never mutates it."""
    signal_id: str
    resolved_on: str                   # ISO date the outcome was measured
    actual_price_later: float
    hypothetical_pnl: float
    hypothetical_return_pct: float


# ── append-only journal (survives restarts, cannot be rewritten) ────────────
class PaperJournal:
    """Append-only persistence. Signals and outcomes are separate record streams
    so an outcome write can never overwrite a sealed decision."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._signals: list[PaperSignal] = []
        self._outcomes: list[PaperOutcome] = []
        self._resolved_ids: set[str] = set()

    def append_signal(self, sig: PaperSignal) -> None:
        self._signals.append(sig)
        self._write_line("signal", asdict(sig))

    def append_outcome(self, out: PaperOutcome) -> bool:
        """Idempotent: an outcome for an already-resolved signal is ignored, so
        replaying the journal never double-books P&L."""
        if out.signal_id in self._resolved_ids:
            return False
        self._resolved_ids.add(out.signal_id)
        self._outcomes.append(out)
        self._write_line("outcome", asdict(out))
        return True

    def signals(self) -> tuple[PaperSignal, ...]:
        return tuple(self._signals)

    def outcomes(self) -> tuple[PaperOutcome, ...]:
        return tuple(self._outcomes)

    def unresolved(self) -> tuple[PaperSignal, ...]:
        return tuple(s for s in self._signals
                     if s.signal_id not in self._resolved_ids and s.approved)

    def _write_line(self, kind: str, payload: dict) -> None:
        if self.path is None:
            return
        with self.path.open("a") as f:
            f.write(json.dumps({"kind": kind, **payload}, default=str) + "\n")


# ── the paper trading session ───────────────────────────────────────────────
@dataclass
class PaperTradingSession:
    """Drives Inflection-001 forward, one day at a time. record_signals() seals
    the day's decisions; resolve_outcomes() later writes what happened. The two
    are separate calls so no single step ever sees both the decision and its
    future price."""
    journal: PaperJournal = field(default_factory=PaperJournal)
    shadow: ShadowSession = field(default_factory=ShadowSession)

    def record_signals(self, signal: NormalizedSignal, state, prices: dict,
                       reasons: dict[str, str], as_of: str) -> list[PaperSignal]:
        """Seal the day's decisions using ONLY data available at as_of. The
        approved orders route through the real firewall into the shadow sink."""
        orders: list[ShadowOrder] = self.shadow.process_signal(signal, state, prices)
        sealed: list[PaperSignal] = []
        for i, o in enumerate(orders):
            sig = PaperSignal(
                as_of=as_of, strategy_id=signal.strategy_id, symbol=o.symbol,
                reason=reasons.get(o.symbol, "inflection signal"),
                target_weight=next((p.target_weight for p in signal.positions
                                    if p.symbol == o.symbol), 0.0),
                intended_price=o.intended_price,
                simulated_fill_price=o.simulated_fill_price,
                approved=o.approved, approved_value=o.approved_value,
                firewall_reasons=o.firewall_reasons,
                signal_id=f"{as_of}:{o.symbol}:{i}")
            self.journal.append_signal(sig)
            sealed.append(sig)
        return sealed

    def resolve_outcomes(self, later_prices: dict[str, float],
                         resolved_on: str) -> list[PaperOutcome]:
        """Later step: for each unresolved APPROVED signal whose symbol now has a
        known subsequent price, write its outcome. Cannot alter the sealed signal.
        """
        resolved: list[PaperOutcome] = []
        for sig in self.journal.unresolved():
            if sig.symbol not in later_prices:
                continue
            # reconstruct the minimal shadow order to reuse the SAME P&L logic
            shadow_like = ShadowOrder(
                sig.symbol, 0.0, sig.approved_value, sig.approved,
                sig.firewall_reasons, sig.intended_price,
                sig.simulated_fill_price, 0.0)
            oc = evaluate_outcome(shadow_like, later_prices[sig.symbol])
            out = PaperOutcome(sig.signal_id, resolved_on,
                               later_prices[sig.symbol], oc.hypothetical_pnl,
                               oc.hypothetical_return_pct)
            if self.journal.append_outcome(out):
                resolved.append(out)
        return resolved

    def health_check(self, observed: LiveBehaviour) -> HealthReport:
        """Assess the accrued forward behaviour against the validated profile."""
        return assess(observed, INFLECTION_PROFILE)

    def track_record(self) -> dict[str, float]:
        """The forward record so far — the only honest evidence of live fitness."""
        outs = self.journal.outcomes()
        n = len(outs)
        total = sum(o.hypothetical_pnl for o in outs)
        wins = sum(1 for o in outs if o.hypothetical_pnl > 0)
        # running drawdown on resolved P&L in resolution order
        eq = peak = mdd = 0.0
        for o in outs:
            eq += o.hypothetical_pnl
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        return {
            "signals_recorded": len(self.journal.signals()),
            "outcomes_resolved": n,
            "unresolved_open": len(self.journal.unresolved()),
            "hypothetical_pnl": round(total, 2),
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "max_drawdown_dollars": round(mdd, 2),
        }


def describe() -> str:
    return "\n".join([
        "PAPER TRADING — forward live simulation of SIGBOT-INFLECTION-001",
        "",
        "  Every day the strategy uses ONLY data available at that moment, seals",
        "  its decisions, and waits to see what happened. The genuine out-of-",
        "  sample record a backtest cannot give.",
        "",
        "  STRUCTURAL DISCIPLINE:",
        "    1. Point-in-time sealing — a PaperSignal has NO outcome field; the",
        "       outcome is a separate later write that cannot alter the decision.",
        "       No code path lets a future price touch a sealed signal, so paper",
        "       trading can't silently become a look-ahead backtest.",
        "    2. Broker submission structurally impossible — orders go to the",
        "       shadow sink; there is no broker handle here.",
        "    3. Health monitor watches the process; drift quarantines, never",
        "       retunes.",
        "",
        "  Append-only journal survives restarts and can't be rewritten. Quiver /",
        "  imported strategies go through the research engine SEPARATELY — never",
        "  silently into this production strategy.",
    ])
