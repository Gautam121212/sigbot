"""Professional Trader Policy — conservative about truth, aggressive about
opportunity, with the aggression gated by evidence the sizing policy itself has
earned.

THREE BRAINS:
  Research Brain  — "what might work?" (creative, can be wrong; elsewhere)
  Trader Brain    — "I want 0..X% exposure." (unrestricted REQUEST)
  Governor        — "how much is AUTHORIZED by evidence right now?"

THE LOAD-BEARING RULE (Rishi's refinement):
  The Governor NEVER treats "more signals agree" as evidence deserving more
  capital. Signal agreement is not conviction. Only the sizing policy's own
  independently-measured, out-of-sample ability to put more capital into better
  outcomes can widen the risk budget. Until a sizing policy earns that proof,
  the Trader's request is clamped to the baseline budget no matter how many
  signals stack.

FOUR STATES per position, the audit spine:
  REQUESTED  — what the Trader Brain wanted
  AUTHORIZED — what the Governor permitted (evidence-gated)
  EXECUTED   — what actually filled
  REALIZED   — what it produced
  => later: "was the Governor too conservative?" / "was conviction useful?"
     become measurable, not opinions.

THREE SEPARATE EVIDENCE QUESTIONS (never conflated):
  signal evidence    — does the signal work?
  sizing evidence    — does larger exposure track better OOS outcomes?
  portfolio evidence — does the sizing policy improve the whole book after
                       costs/drawdown/correlation?
  A policy can pass sizing and still fail portfolio. Both gate the budget.

The budget ladder is CONFIG, not ideology. The current conservative budget is
SIGBOT's launch state, not its identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ── the risk-budget ladder (configuration, not hard-coded) ──────────────────
class EvidenceRung(str, Enum):
    """Rungs of the ladder. A policy climbs only by earning the proof at each."""
    UNPROVEN = "UNPROVEN"                       # no capital
    BACKTEST_ONLY = "BACKTEST_ONLY"             # paper sizing only
    OOS_PROVEN_SIGNAL = "OOS_PROVEN_SIGNAL"     # baseline live-candidate budget
    OOS_PROVEN_SIZING = "OOS_PROVEN_SIZING"     # expanded budget
    PAPER_CONFIRMED_SIZING = "PAPER_CONFIRMED_SIZING"  # further expansion
    LIVE_VALIDATED = "LIVE_VALIDATED"           # normal operating range


# default ladder (per-position cap, fraction of capital). Config-overridable.
DEFAULT_BUDGET_LADDER: dict[EvidenceRung, float] = {
    EvidenceRung.UNPROVEN: 0.00,
    EvidenceRung.BACKTEST_ONLY: 0.00,           # paper only — no live capital
    EvidenceRung.OOS_PROVEN_SIGNAL: 0.02,       # the current launch budget
    EvidenceRung.OOS_PROVEN_SIZING: 0.05,
    EvidenceRung.PAPER_CONFIRMED_SIZING: 0.08,
    EvidenceRung.LIVE_VALIDATED: 0.12,
}


@dataclass(frozen=True)
class SizingEvidence:
    """What the sizing POLICY has earned — distinct from signal evidence.
    The Governor reads this, never the signal stack, to set the budget rung."""
    signal_oos_proven: bool = False
    sizing_oos_proven: bool = False       # bigger positions tracked better OOS
    sizing_robust: bool = False           # survived time/regime/asset subsamples
    portfolio_oos_proven: bool = False    # improved the whole book OOS
    paper_confirmed: bool = False
    live_validated: bool = False

    def rung(self) -> EvidenceRung:
        """The highest rung the EARNED evidence supports. Each step requires all
        lower proofs. Sizing budget needs BOTH sizing-OOS AND robustness AND
        portfolio-OOS — a sizing scheme that passes sizing but fails portfolio
        stays at the signal rung."""
        if not self.signal_oos_proven:
            return EvidenceRung.BACKTEST_ONLY
        if self.live_validated:
            return EvidenceRung.LIVE_VALIDATED
        sizing_ok = (self.sizing_oos_proven and self.sizing_robust
                     and self.portfolio_oos_proven)
        if self.paper_confirmed and sizing_ok:
            return EvidenceRung.PAPER_CONFIRMED_SIZING
        if sizing_ok:
            return EvidenceRung.OOS_PROVEN_SIZING
        return EvidenceRung.OOS_PROVEN_SIGNAL


# ── the four-state position record ──────────────────────────────────────────
@dataclass
class PositionDecision:
    """The REQUESTED→AUTHORIZED→EXECUTED→REALIZED audit spine for one position."""
    symbol: str
    requested: float                      # Trader Brain's desired fraction
    authorized: float = 0.0               # Governor's permitted fraction
    executed: float = 0.0                 # what filled
    realized_return: float | None = None  # outcome (filled later)
    clamp_reason: str = ""                # why authorized < requested, if so

    def was_clamped(self) -> bool:
        return self.authorized < self.requested - 1e-9

    def conviction_used(self) -> bool | None:
        """Was the Trader's extra conviction (request above baseline) useful?
        Measurable once realized — but only meaningful when NOT clamped."""
        if self.realized_return is None or self.was_clamped():
            return None
        return self.realized_return > 0


# ── the Governor ─────────────────────────────────────────────────────────────
@dataclass
class Governor:
    """Evidence-gated authorization. The budget comes ONLY from SizingEvidence —
    never from how many signals agree. Also enforces liquidity / portfolio /
    drawdown limits, which can lower (never raise) the authorization."""
    evidence: SizingEvidence
    ladder: dict[EvidenceRung, float] = field(
        default_factory=lambda: dict(DEFAULT_BUDGET_LADDER))
    drawdown_locked: bool = False         # risk-off state lowers budget to 0

    def budget(self) -> float:
        if self.drawdown_locked:
            return 0.0
        return self.ladder[self.evidence.rung()]

    def authorize(self, symbol: str, requested: float, *,
                  liquidity_cap: float = 1.0,
                  portfolio_cap: float = 1.0) -> PositionDecision:
        """Clamp the request to min(evidence budget, liquidity, portfolio).
        Signal agreement is NOT an input — by construction it cannot raise the
        authorization."""
        budget = self.budget()
        caps = {"evidence budget": budget, "liquidity": liquidity_cap,
                "portfolio": portfolio_cap}
        authorized = min(requested, *caps.values())
        reason = ""
        if authorized < requested - 1e-9:
            binding = min(caps, key=lambda k: caps[k])
            reason = f"clamped by {binding} ({caps[binding]:.2%})"
        return PositionDecision(symbol=symbol, requested=requested,
                                authorized=round(authorized, 6),
                                clamp_reason=reason)


# ── the sizing-policy certification (its own artifact) ──────────────────────
@dataclass
class SizingPolicyResult:
    """Whether a variable-sizing policy beat uniform sizing OOS and at the
    portfolio level. This is the artifact that unlocks budget — tested the same
    brutal way as any alpha hypothesis."""
    uniform_cagr: float
    variable_cagr: float
    uniform_sharpe: float
    variable_sharpe: float
    uniform_maxdd: float
    variable_maxdd: float
    # the key test: do bigger positions actually earn more, OOS?
    top_decile_oos_return: float = 0.0
    bottom_decile_oos_return: float = 0.0
    robust_across_subsamples: bool = False

    def sizing_adds_value_oos(self) -> bool:
        """Variable must beat uniform on risk-adjusted return AND the bigger
        positions must actually outperform the smaller ones OOS. A policy that
        merely put more into lucky trades fails the decile test on holdout."""
        beats = (self.variable_sharpe > self.uniform_sharpe
                 and self.variable_cagr > self.uniform_cagr)
        bigger_better = self.top_decile_oos_return > self.bottom_decile_oos_return
        return beats and bigger_better

    def portfolio_improves(self) -> bool:
        """Variable improves the whole book: better Sharpe without materially
        worse drawdown."""
        return (self.variable_sharpe > self.uniform_sharpe
                and self.variable_maxdd <= self.uniform_maxdd * 1.1)

    def verdict(self) -> str:
        if not self.robust_across_subsamples:
            return "FAIL — not robust across subsamples"
        if not self.sizing_adds_value_oos():
            return "FAIL — sizing does not add value OOS"
        if not self.portfolio_improves():
            return "FAIL — no portfolio-level improvement"
        return "PASS — variable sizing earns expanded budget"


def describe() -> str:
    return "\n".join([
        "PROFESSIONAL TRADER POLICY — conservative about truth, aggressive",
        "about opportunity, aggression gated by earned sizing evidence.",
        "",
        "  Trader Brain REQUESTS any exposure (0..X%); the Governor AUTHORIZES",
        "  from the evidence budget only. Signal agreement is NEVER an input to",
        "  the budget — only the sizing policy's own OOS + portfolio proof widens",
        "  it. Four-state spine: REQUESTED -> AUTHORIZED -> EXECUTED -> REALIZED.",
        "",
        "  Budget ladder (config, not ideology): UNPROVEN/BACKTEST=0,",
        "  OOS_PROVEN_SIGNAL=launch budget, OOS_PROVEN_SIZING/PAPER/LIVE widen",
        "  only as the sizing policy passes sizing-OOS AND robustness AND",
        "  portfolio-OOS. A scheme that passes sizing but fails portfolio stays",
        "  at the signal rung. The current conservative budget is the LAUNCH",
        "  STATE, not SIGBOT's identity.",
        "",
        "  SizingPolicyResult is a certifiable artifact: variable sizing must",
        "  beat uniform OOS, its bigger positions must outperform its smaller",
        "  ones on holdout (not just capture lucky trades), and it must survive",
        "  subsamples — else no budget. Uniform sizing is the permanent control.",
    ])
