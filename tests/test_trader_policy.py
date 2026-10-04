"""Professional Trader Policy — evidence-gated sizing, signal agreement cannot
buy capital, sizing policy is a certifiable artifact."""
from sigbot.trader_policy import (
    DEFAULT_BUDGET_LADDER, EvidenceRung, Governor, PositionDecision,
    SizingEvidence, SizingPolicyResult)


# ── the load-bearing rule: signal agreement does not widen the budget ───────
def test_signal_agreement_does_not_buy_capital():
    # signal proven, sizing NOT — a big request clamps to the signal budget
    gov = Governor(evidence=SizingEvidence(signal_oos_proven=True))
    d = gov.authorize("AAPL", requested=0.12)
    assert d.authorized == DEFAULT_BUDGET_LADDER[EvidenceRung.OOS_PROVEN_SIGNAL]
    assert d.was_clamped()
    assert "evidence budget" in d.clamp_reason


def test_unproven_signal_gets_zero_live_budget():
    gov = Governor(evidence=SizingEvidence())        # nothing proven
    assert gov.budget() == 0.0
    d = gov.authorize("X", requested=0.10)
    assert d.authorized == 0.0


# ── budget widens only when the sizing policy earns it ──────────────────────
def test_sizing_oos_widens_budget():
    ev = SizingEvidence(signal_oos_proven=True, sizing_oos_proven=True,
                        sizing_robust=True, portfolio_oos_proven=True)
    gov = Governor(evidence=ev)
    assert gov.evidence.rung() == EvidenceRung.OOS_PROVEN_SIZING
    assert gov.budget() == DEFAULT_BUDGET_LADDER[EvidenceRung.OOS_PROVEN_SIZING]


def test_sizing_without_portfolio_proof_stays_at_signal_rung():
    # passes sizing-OOS + robust but NOT portfolio -> no wider budget
    ev = SizingEvidence(signal_oos_proven=True, sizing_oos_proven=True,
                        sizing_robust=True, portfolio_oos_proven=False)
    gov = Governor(evidence=ev)
    assert gov.evidence.rung() == EvidenceRung.OOS_PROVEN_SIGNAL


def test_sizing_without_robustness_stays_at_signal_rung():
    ev = SizingEvidence(signal_oos_proven=True, sizing_oos_proven=True,
                        sizing_robust=False, portfolio_oos_proven=True)
    gov = Governor(evidence=ev)
    assert gov.evidence.rung() == EvidenceRung.OOS_PROVEN_SIGNAL


def test_paper_confirmation_widens_further():
    ev = SizingEvidence(signal_oos_proven=True, sizing_oos_proven=True,
                        sizing_robust=True, portfolio_oos_proven=True,
                        paper_confirmed=True)
    gov = Governor(evidence=ev)
    assert gov.evidence.rung() == EvidenceRung.PAPER_CONFIRMED_SIZING


def test_live_validated_is_top_rung():
    ev = SizingEvidence(signal_oos_proven=True, sizing_oos_proven=True,
                        sizing_robust=True, portfolio_oos_proven=True,
                        paper_confirmed=True, live_validated=True)
    assert Governor(evidence=ev).evidence.rung() == EvidenceRung.LIVE_VALIDATED


# ── the ladder is monotonic ──────────────────────────────────────────────────
def test_budget_ladder_monotonic():
    order = [EvidenceRung.UNPROVEN, EvidenceRung.BACKTEST_ONLY,
             EvidenceRung.OOS_PROVEN_SIGNAL, EvidenceRung.OOS_PROVEN_SIZING,
             EvidenceRung.PAPER_CONFIRMED_SIZING, EvidenceRung.LIVE_VALIDATED]
    budgets = [DEFAULT_BUDGET_LADDER[r] for r in order]
    assert budgets == sorted(budgets)


# ── drawdown lock overrides everything ──────────────────────────────────────
def test_drawdown_lock_forces_zero():
    ev = SizingEvidence(signal_oos_proven=True, sizing_oos_proven=True,
                        sizing_robust=True, portfolio_oos_proven=True,
                        live_validated=True)
    gov = Governor(evidence=ev, drawdown_locked=True)
    assert gov.budget() == 0.0


# ── liquidity / portfolio caps can only lower ───────────────────────────────
def test_liquidity_cap_binds():
    ev = SizingEvidence(signal_oos_proven=True, sizing_oos_proven=True,
                        sizing_robust=True, portfolio_oos_proven=True)
    gov = Governor(evidence=ev)         # budget 5%
    d = gov.authorize("X", requested=0.12, liquidity_cap=0.03)
    assert d.authorized == 0.03
    assert "liquidity" in d.clamp_reason


def test_caps_never_raise_above_budget():
    gov = Governor(evidence=SizingEvidence(signal_oos_proven=True))  # 2%
    d = gov.authorize("X", requested=0.12, liquidity_cap=0.5,
                      portfolio_cap=0.5)
    assert d.authorized == 0.02         # budget still binds


# ── the four-state spine ─────────────────────────────────────────────────────
def test_position_states():
    d = PositionDecision("X", requested=0.08, authorized=0.03, executed=0.028,
                         realized_return=0.041)
    assert d.was_clamped()
    # conviction_used is only meaningful when NOT clamped
    assert d.conviction_used() is None


def test_conviction_measurable_when_not_clamped():
    d = PositionDecision("X", requested=0.02, authorized=0.02, executed=0.02,
                         realized_return=0.03)
    assert not d.was_clamped()
    assert d.conviction_used() is True


# ── sizing policy certification ─────────────────────────────────────────────
def test_lucky_trade_capture_fails_decile():
    # variable beats uniform on CAGR but bigger positions did WORSE OOS
    r = SizingPolicyResult(12, 15, 1.2, 1.4, 0.2, 0.2,
                           top_decile_oos_return=0.01,
                           bottom_decile_oos_return=0.03,
                           robust_across_subsamples=True)
    assert not r.sizing_adds_value_oos()
    assert "FAIL" in r.verdict()


def test_non_robust_fails():
    r = SizingPolicyResult(12, 15, 1.2, 1.5, 0.2, 0.19,
                           top_decile_oos_return=0.06,
                           bottom_decile_oos_return=0.01,
                           robust_across_subsamples=False)
    assert "not robust" in r.verdict()


def test_portfolio_regression_fails():
    # bigger positions outperform OOS but drawdown blows out
    r = SizingPolicyResult(12, 15, 1.2, 1.25, 0.2, 0.30,
                           top_decile_oos_return=0.06,
                           bottom_decile_oos_return=0.01,
                           robust_across_subsamples=True)
    assert not r.portfolio_improves()
    assert "FAIL" in r.verdict()


def test_genuine_sizing_passes():
    r = SizingPolicyResult(12, 15, 1.2, 1.5, 0.2, 0.19,
                           top_decile_oos_return=0.06,
                           bottom_decile_oos_return=0.01,
                           robust_across_subsamples=True)
    assert r.sizing_adds_value_oos()
    assert r.portfolio_improves()
    assert "PASS" in r.verdict()


# ── config override ──────────────────────────────────────────────────────────
def test_ladder_is_config_not_hardcoded():
    custom = dict(DEFAULT_BUDGET_LADDER)
    custom[EvidenceRung.OOS_PROVEN_SIGNAL] = 0.01   # more conservative launch
    gov = Governor(evidence=SizingEvidence(signal_oos_proven=True),
                   ladder=custom)
    assert gov.budget() == 0.01
