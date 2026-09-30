"""Live health monitor — detect when the validated strategy stops behaving like
the validated strategy. Detect, stop, investigate — never tweak.

The last deterministic gate before real money. Its job is NOT to find trades or
improve returns. It is to answer one question continuously:

    "Is SIGBOT-INFLECTION-001 still behaving like the process we validated?"

THE KEY DISTINCTION (getting this wrong defeats the purpose):
  * "Losing money WITHIN the validated distribution" -> NORMAL. Inflection has a
    ~14% forward expectation and a Monte-Carlo 95th-pct drawdown near 40%. Long
    losing stretches are EXPECTED. A monitor that pauses on drawdown alone would
    fire during exactly the drawdowns the research predicted — pausing a healthy
    strategy for behaving as designed.
  * "Behaving UNLIKE the validated PROCESS" -> DRIFT. The characteristics —
    win rate, signal frequency, position concentration, execution drag — have
    moved outside the bands the backtest established.

So the monitor watches PROCESS characteristics, not just return level. It is also
SYMMETRIC: a strategy suddenly making far MORE than expected (win rate spikes to
90%, signals fire 5x as often) is ALSO drifting — that is how the 2020-Q2 COVID
quarter looked, and it was not a thing to trust.

ON DRIFT: the monitor QUARANTINES (pauses) and records that the strategy is
outside its previously observed distribution. It NEVER adjusts parameters to
"fix" the deterioration. Same philosophy as everywhere else: don't explain away
failure, detect it and stop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class HealthState(str, Enum):
    HEALTHY = "healthy"                # within the validated distribution
    WARNING = "warning"               # one characteristic drifting
    QUARANTINED = "quarantined"       # material drift -> paused, investigate


# ── the validated baseline: what the backtest established ───────────────────
@dataclass(frozen=True)
class ValidatedProfile:
    """The behavioural fingerprint from validation. Bands are the normal range,
    NOT targets. Live behaviour outside a band is drift — in EITHER direction."""
    win_rate: float                    # e.g. 59.4
    win_rate_band: float               # +/- tolerance, e.g. 12 (points)
    signals_per_month: float           # e.g. 12
    signals_band: float                # +/- tolerance
    avg_position_pct: float            # e.g. 4.0 (mean single-name weight)
    position_band: float               # +/- tolerance
    execution_drag_bps: float          # expected friction, e.g. 30
    drag_band_bps: float               # +/- tolerance
    # return distribution (from Monte Carlo) — used to judge whether a loss is
    # WITHIN the validated distribution, not to alarm on losses directly
    forward_cagr_p5: float             # e.g. 5.3
    max_drawdown_p95: float            # e.g. 39.9  (normal worst-case DD)


# SIGBOT-INFLECTION-001's validated profile (from this session's research).
INFLECTION_PROFILE = ValidatedProfile(
    win_rate=59.4, win_rate_band=12.0,
    signals_per_month=12.0, signals_band=8.0,
    avg_position_pct=4.0, position_band=3.0,
    execution_drag_bps=30.0, drag_band_bps=25.0,
    forward_cagr_p5=5.3, max_drawdown_p95=39.9)


# ── live behaviour being observed ───────────────────────────────────────────
@dataclass(frozen=True)
class LiveBehaviour:
    win_rate: float
    signals_per_month: float
    avg_position_pct: float
    execution_drag_bps: float
    current_drawdown_pct: float


@dataclass(frozen=True)
class DriftFinding:
    characteristic: str
    expected: str
    observed: str
    direction: str                     # "above" or "below" the band


@dataclass(frozen=True)
class HealthReport:
    state: HealthState
    findings: tuple[DriftFinding, ...]
    checked_at: datetime

    def is_paused(self) -> bool:
        return self.state == HealthState.QUARANTINED


def _band_check(name: str, observed: float, expected: float,
                band: float) -> DriftFinding | None:
    """Symmetric band check — flags drift ABOVE or BELOW the validated range."""
    if observed > expected + band:
        return DriftFinding(name, f"{expected:g}+/-{band:g}", f"{observed:g}", "above")
    if observed < expected - band:
        return DriftFinding(name, f"{expected:g}+/-{band:g}", f"{observed:g}", "below")
    return None


def assess(live: LiveBehaviour, profile: ValidatedProfile = INFLECTION_PROFILE,
           now_fn=None) -> HealthReport:
    """Deterministic health assessment. Watches PROCESS characteristics
    symmetrically. A drawdown WITHIN the validated 95th-pct is NOT drift; a
    drawdown beyond it IS. Never adjusts the strategy — only reports."""
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    findings: list[DriftFinding] = []

    for f in (
        _band_check("win_rate", live.win_rate, profile.win_rate,
                    profile.win_rate_band),
        _band_check("signals_per_month", live.signals_per_month,
                    profile.signals_per_month, profile.signals_band),
        _band_check("avg_position_pct", live.avg_position_pct,
                    profile.avg_position_pct, profile.position_band),
        _band_check("execution_drag_bps", live.execution_drag_bps,
                    profile.execution_drag_bps, profile.drag_band_bps),
    ):
        if f is not None:
            findings.append(f)

    # Drawdown: only a drift if BEYOND the validated normal worst-case. A loss
    # inside the distribution is expected and is NOT flagged.
    if live.current_drawdown_pct > profile.max_drawdown_p95:
        findings.append(DriftFinding(
            "drawdown", f"<= {profile.max_drawdown_p95:g}% (validated 95th pct)",
            f"{live.current_drawdown_pct:g}%", "above"))

    # State: any single drift -> WARNING; two or more -> QUARANTINE. A drawdown
    # beyond the validated worst-case is material on its own.
    material_dd = any(f.characteristic == "drawdown" for f in findings)
    if not findings:
        state = HealthState.HEALTHY
    elif len(findings) >= 2 or material_dd:
        state = HealthState.QUARANTINED
    else:
        state = HealthState.WARNING
    return HealthReport(state, tuple(findings), now)


# ── append-only health ledger ───────────────────────────────────────────────
@dataclass
class HealthLedger:
    """Records every assessment and every state transition. Append-only — a
    quarantine event is preserved for investigation, never overwritten."""
    _reports: list[HealthReport] = field(default_factory=list)

    def append(self, report: HealthReport) -> None:
        self._reports.append(report)

    def all(self) -> tuple[HealthReport, ...]:
        return tuple(self._reports)

    def quarantines(self) -> tuple[HealthReport, ...]:
        return tuple(r for r in self._reports if r.state == HealthState.QUARANTINED)

    def last_state(self) -> HealthState:
        return self._reports[-1].state if self._reports else HealthState.HEALTHY


def monitor_allows_trading(state: HealthState) -> bool:
    """The firewall consults this too: a quarantined strategy authorizes no new
    capital until an operator investigates and clears it."""
    return state != HealthState.QUARANTINED


def describe() -> str:
    return "\n".join([
        "LIVE HEALTH MONITOR — detect drift from the validated process, then stop",
        "",
        "  Answers 'is SIGBOT-INFLECTION-001 still behaving like what we",
        "  validated?' — NOT 'is it making money?'. Watches PROCESS traits (win",
        "  rate, signal frequency, position concentration, execution drag)",
        "  SYMMETRICALLY: drifting ABOVE the band (a suspicious hot streak) is",
        "  drift too, not just drifting below.",
        "",
        "  A drawdown WITHIN the validated 95th-pct (~40%) is NORMAL and is NOT",
        "  flagged — pausing on expected drawdown would defeat the purpose. Only a",
        "  drawdown BEYOND the validated worst-case is drift.",
        "",
        "  On drift: QUARANTINE and record. It NEVER tweaks the strategy to",
        "  explain away deterioration. Detect, stop, investigate — the same",
        "  philosophy as every other gate. Quarantine blocks new capital via the",
        "  firewall until an operator clears it.",
    ])
