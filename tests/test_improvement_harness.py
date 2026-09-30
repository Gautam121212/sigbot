"""Improvement harness — enforced one-gap-at-a-time discipline.

Covers the five required areas: experiment isolation, split leakage, parameter
mutation, reproducibility, and rejection of bundled changes."""
import pytest

from sigbot.improvement_harness import (
    BundledChangeError, Change, Component, ExperimentConfig, LockedSplit,
    ResearchLedger, SplitConfig, SplitLeakageError, SplitResult, Verdict,
    decide, run_experiment)


def _splits():
    return SplitConfig("2019-12-31", "2021-12-31", "2024-12-31")


def _one_change():
    return [Change(Component.EXECUTION, "same->next bar", "same-bar", "next-bar")]


# ── 1. EXPERIMENT ISOLATION ─────────────────────────────────────────────────
def test_single_change_is_accepted():
    cfg = ExperimentConfig("B", _one_change(), _splits())
    cfg.assert_single_change()          # does not raise


def test_zero_changes_rejected():
    cfg = ExperimentConfig("B", [], _splits())
    with pytest.raises(BundledChangeError):
        cfg.assert_single_change()


# ── 2. REJECTION OF BUNDLED CHANGES ─────────────────────────────────────────
def test_bundled_change_rejected_before_execution():
    cfg = ExperimentConfig("B", [
        Change(Component.EXECUTION, "x", "a", "b"),
        Change(Component.SIZING, "y", "c", "d")], _splits())
    with pytest.raises(BundledChangeError):
        cfg.assert_single_change()


def test_run_experiment_refuses_bundle():
    """The harness entry point rejects a bundle before touching any data."""
    cfg = ExperimentConfig("B", [
        Change(Component.LIQUIDITY, "x", "a", "b"),
        Change(Component.EXIT_RULE, "y", "c", "d")], _splits())
    ledger = ResearchLedger()
    with pytest.raises(BundledChangeError):
        run_experiment(cfg, lambda: None, lambda: None, ledger)
    assert len(ledger) == 0             # nothing recorded — never ran


# ── 3. SPLIT LEAKAGE ────────────────────────────────────────────────────────
def test_sealed_oos_cannot_be_read_during_fitting():
    locked = LockedSplit(1.6)
    with pytest.raises(SplitLeakageError):
        locked.read()


def test_oos_readable_only_after_unseal():
    locked = LockedSplit(1.6)
    locked.unseal()
    assert locked.read() == 1.6


def test_splits_must_be_ordered():
    with pytest.raises(ValueError):
        SplitConfig("2021-12-31", "2020-12-31", "2024-12-31")  # dev > val


# ── 4. PARAMETER MUTATION (tamper-evidence via hash) ────────────────────────
def test_freeze_hash_is_stable_for_same_config():
    c1 = ExperimentConfig("B", _one_change(), _splits())
    c2 = ExperimentConfig("B", _one_change(), _splits())
    assert c1.freeze() == c2.freeze()


def test_freeze_hash_changes_if_param_mutated():
    c1 = ExperimentConfig("B", _one_change(), _splits())
    h1 = c1.freeze()
    c2 = ExperimentConfig("B", [Change(Component.EXECUTION, "same->next bar",
                                       "same-bar", "T+2")], _splits())  # mutated
    assert c2.freeze() != h1


def test_freeze_hash_changes_if_seed_mutated():
    c1 = ExperimentConfig("B", _one_change(), _splits(), seed=42)
    c2 = ExperimentConfig("B", _one_change(), _splits(), seed=43)
    assert c1.freeze() != c2.freeze()


# ── 5. REPRODUCIBILITY & DECISION ───────────────────────────────────────────
def _base():
    return (SplitResult(5.0, 1.5, 17.0, 59.0, 100),
            SplitResult(5.0, 1.5, 17.0, 59.0, 100),
            LockedSplit(1.5))


def _variant_better():
    return (SplitResult(6.0, 1.7, 16.0, 60.0, 100),
            SplitResult(6.0, 1.7, 16.0, 60.0, 100),
            LockedSplit(1.7))


def _variant_worse():
    return (SplitResult(9.0, 1.2, 25.0, 45.0, 100),
            SplitResult(9.0, 1.2, 25.0, 45.0, 100),
            LockedSplit(1.2))


def test_experiment_is_reproducible():
    """Same inputs -> same verdict and same config hash."""
    cfg1 = ExperimentConfig("B", _one_change(), _splits())
    cfg2 = ExperimentConfig("B", _one_change(), _splits())
    r1 = run_experiment(cfg1, _base, _variant_better, ResearchLedger())
    r2 = run_experiment(cfg2, _base, _variant_better, ResearchLedger())
    assert r1.verdict == r2.verdict
    assert r1.config_hash == r2.config_hash


def test_better_variant_passes():
    r = run_experiment(ExperimentConfig("B", _one_change(), _splits()),
                       _base, _variant_better, ResearchLedger())
    assert r.verdict == Verdict.PASS


def test_higher_cagr_but_worse_risk_is_rejected():
    """NEVER CAGR alone: +9% return but Sharpe down, DD up, win-rate down."""
    r = run_experiment(ExperimentConfig("B", _one_change(), _splits()),
                       _base, _variant_worse, ResearchLedger())
    assert r.verdict == Verdict.REJECT


def test_thin_sample_rejected():
    def thin():
        return (SplitResult(6.0, 1.7, 16.0, 60.0, 10),
                SplitResult(6.0, 1.7, 16.0, 60.0, 10), LockedSplit(1.7))
    r = run_experiment(ExperimentConfig("B", _one_change(), _splits()),
                       _base, thin, ResearchLedger())
    assert r.verdict == Verdict.REJECT


# ── immutable ledger records failures too ───────────────────────────────────
def test_ledger_records_failures():
    ledger = ResearchLedger()
    run_experiment(ExperimentConfig("B", _one_change(), _splits()),
                   _base, _variant_worse, ledger)
    assert len(ledger) == 1
    assert len(ledger.rejections()) == 1


def test_decide_never_uses_cagr_alone():
    """A variant with huge return but worse Sharpe is rejected."""
    base = SplitResult(5.0, 1.5, 17.0, 59.0, 100)
    high_cagr_bad_risk = SplitResult(20.0, 1.1, 30.0, 50.0, 100)
    verdict, reasons = decide(base, high_cagr_bad_risk)
    assert verdict == Verdict.REJECT
