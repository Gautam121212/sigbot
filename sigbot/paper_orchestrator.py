"""Paper orchestrator — the real-time forward runner for SIGBOT-INFLECTION-001.

Runs the validated strategy forward in real market time so reality can judge it.
Builds only on shipped components (paper_trading, shadow, firewall, health
monitor); adds NO new alpha, NO broker.

THE DESIGN CONSTRAINT THAT MAKES THE RECORD MEANINGFUL — TWO CLOCKS:

  Inflection is a QUARTERLY, event-driven signal (3q margin + 2q revenue accel).
  A signal changes ONLY when a company files a new quarterly report. So the
  runner must NOT reseal a fresh decision every day — that would log ~250
  near-duplicate "decisions" a year for what is really ~12 independent quarterly
  entries, making the forward win-rate/frequency stats incomparable to the
  backtest and false-quarantining the health monitor on day one.

  SIGNAL CLOCK (event-driven / quarterly): a new PaperSignal is sealed ONLY when
  the fundamental signal set actually CHANGES vs the currently held book. Same
  fundamentals -> no new decision, positions simply continue.

  MONITORING CLOCK (daily): every trading day the runner marks open positions at
  the day's close, accrues P&L, resolves positions whose hold window closed, and
  runs the health monitor. It marks and monitors — it never re-decides.

Tomorrow's information can never modify today's sealed decision (enforced by
paper_trading's separate signal/outcome records).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .live_health_monitor import HealthReport, LiveBehaviour
from .paper_trading import PaperTradingSession
from .risk_firewall import PortfolioState
from .strategy_adapter import NormalizedSignal


# ── the two-clock signal-change detector ────────────────────────────────────
def signal_set_changed(previous: NormalizedSignal | None,
                       current: NormalizedSignal) -> bool:
    """True only when the fundamental signal set differs from the held book.
    Same set of (symbol, weight) -> no new decision. This is what keeps the
    signal clock quarterly instead of daily."""
    if previous is None:
        return bool(current.positions)
    prev = {(p.symbol, round(p.target_weight, 6)) for p in previous.positions}
    cur = {(p.symbol, round(p.target_weight, 6)) for p in current.positions}
    return prev != cur


@dataclass(frozen=True)
class DailyReport:
    """One monitoring-clock tick: the forward record so far plus health."""
    as_of: str
    new_signals_sealed: int            # 0 on most days (quarterly signal clock)
    open_positions: int
    resolved_today: int
    track_record: dict[str, float]
    health: HealthReport
    live_vs_historical: dict[str, str]  # each trait: within / drifting


# ── historical bands for the live-vs-historical comparison ──────────────────
# From the validated INFLECTION_PROFILE — the process the forward record must
# still resemble. (value, band) pairs.
HISTORICAL_BANDS = {
    "win_rate": (59.4, 12.0),
    "signals_per_month": (12.0, 8.0),
    "avg_position_pct": (4.0, 3.0),
    "execution_drag_bps": (30.0, 25.0),
}


def _compare_to_band(name: str, observed: float) -> str:
    expected, band = HISTORICAL_BANDS[name]
    if observed > expected + band:
        return f"DRIFTING above ({observed:g} vs {expected:g}+/-{band:g})"
    if observed < expected - band:
        return f"DRIFTING below ({observed:g} vs {expected:g}+/-{band:g})"
    return f"within band ({observed:g} vs {expected:g}+/-{band:g})"


# ── the orchestrator ────────────────────────────────────────────────────────
@dataclass
class PaperOrchestrator:
    """Drives Inflection-001 forward. daily_signal_cycle reseals ONLY on a real
    signal change; daily_monitoring_cycle marks/resolves/monitors every day."""
    session: PaperTradingSession = field(default_factory=PaperTradingSession)
    last_signal: NormalizedSignal | None = field(default=None, init=False)

    # ── job 2: daily signal cycle (event-driven reseal) ──────────────────────
    def daily_signal_cycle(self, todays_signal: NormalizedSignal,
                           state: PortfolioState, prices: dict[str, float],
                           reasons: dict[str, str], as_of: str) -> int:
        """Seal today's decision ONLY if the fundamental signal set changed.
        Returns the number of new signals sealed (0 on most days)."""
        if not signal_set_changed(self.last_signal, todays_signal):
            return 0                   # same fundamentals -> positions continue
        sealed = self.session.record_signals(todays_signal, state, prices,
                                             reasons, as_of)
        self.last_signal = todays_signal
        return len(sealed)

    # ── job 3: outcome cycle (separate, later) ───────────────────────────────
    def resolve(self, later_prices: dict[str, float], resolved_on: str) -> int:
        return len(self.session.resolve_outcomes(later_prices, resolved_on))

    # ── job 4: daily monitoring + report ─────────────────────────────────────
    def daily_monitoring_cycle(self, as_of: str, new_signals: int,
                               observed_this_period: LiveBehaviour) -> DailyReport:
        """Mark, monitor, report — never re-decide. Feeds the accrued record to
        the health monitor and compares each trait to its historical band."""
        tr = self.session.track_record()
        health = self.session.health_check(observed_this_period)
        comparison = {
            "win_rate": _compare_to_band("win_rate", observed_this_period.win_rate),
            "signals_per_month": _compare_to_band(
                "signals_per_month", observed_this_period.signals_per_month),
            "avg_position_pct": _compare_to_band(
                "avg_position_pct", observed_this_period.avg_position_pct),
            "execution_drag_bps": _compare_to_band(
                "execution_drag_bps", observed_this_period.execution_drag_bps),
        }
        return DailyReport(
            as_of=as_of, new_signals_sealed=new_signals,
            open_positions=len(self.session.journal.unresolved()),
            resolved_today=0, track_record=tr, health=health,
            live_vs_historical=comparison)


def describe() -> str:
    return "\n".join([
        "PAPER ORCHESTRATOR — forward runner for SIGBOT-INFLECTION-001",
        "",
        "  TWO CLOCKS (what makes the forward record comparable to the backtest):",
        "    SIGNAL CLOCK (quarterly/event-driven): reseals a decision ONLY when",
        "      the fundamental signal set actually changes — not every day.",
        "      Inflection fires on a new quarterly filing, so daily reseal would",
        "      log ~250 duplicate decisions for ~12 real ones and false-",
        "      quarantine the health monitor on frequency.",
        "    MONITORING CLOCK (daily): mark open positions, accrue P&L, resolve",
        "      closed holds, run the health monitor. Marks and monitors — never",
        "      re-decides.",
        "",
        "  Reports LIVE PAPER vs HISTORICAL BAND for win rate, signal frequency,",
        "  concentration and execution drag — 'is the PROCESS still the process we",
        "  validated?', not just 'are we profitable?'. No broker, no new alpha.",
    ])
