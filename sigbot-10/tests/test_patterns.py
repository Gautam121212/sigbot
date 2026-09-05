"""Tests for the pattern registry.

`test_confirmation_removes_selection_bias` is the reason this module exists.
It runs the full discovery-then-confirm pipeline over a population of patterns
whose true hit rates are known, and asserts that what the system *quotes* is
close to the truth rather than to the number that got the pattern promoted.
"""
from __future__ import annotations

import numpy as np
import pytest

from sigbot.patterns import PatternRegistry, RegistryRules, Stage
from sigbot.stats import wilson_interval


@pytest.fixture
def reg(tmp_path):
    return PatternRegistry(tmp_path / "p.db")


def feed(reg, key, outcomes, model="contagion", symbol="X", offset=0):
    stage = None
    for i, hit in enumerate(outcomes):
        stage = reg.record(key, model, symbol, f"bar-{offset + i}", bool(hit))
    return stage


# ------------------------------------------------------------ idempotency

def test_replaying_the_same_observation_changes_nothing(reg):
    """The duplicate-shock bug: a collector re-reading recent history on every
    cron run must not inflate the sample size that gates promotion."""
    for _ in range(6):  # six cron runs a day, same three shocks each time
        for i in range(3):
            reg.record("A->B", "contagion", "B", f"bar-{i}", True)
    rec = reg.get("A->B")
    assert rec.disc_n == 3, f"observations inflated to {rec.disc_n}"
    assert rec.disc_hits == 3


def test_observation_id_must_identify_the_event(reg):
    """Distinct events accumulate; the same event does not."""
    for i in range(50):
        reg.record("A->C", "contagion", "C", f"bar-{i}", i % 2 == 0)
    assert reg.get("A->C").disc_n == 50


# ---------------------------------------------------------------- pruning

def test_clear_failure_is_pruned(reg):
    stage = feed(reg, "bad", [False] * 16 + [True] * 4)
    assert stage is Stage.PRUNED
    assert reg.get("bad").stage is Stage.PRUNED


def test_pruned_pattern_stays_dead(reg):
    feed(reg, "bad", [False] * 20)
    for i in range(200):
        reg.record("bad", "contagion", "X", f"later-{i}", True)
    assert reg.get("bad").stage is Stage.PRUNED, "a pruned pattern must not revive"
    assert reg.get("bad").disc_n == 20


# ------------------------------------------------- promotion and reset

def test_promotion_resets_the_counters(reg):
    rng = np.random.default_rng(0)
    key = "strong"
    for i in range(400):
        if reg.record(key, "contagion", "D", f"b{i}", rng.random() < 0.85) is not Stage.DISCOVERY:
            break
    rec = reg.get(key)
    assert rec.stage is not Stage.DISCOVERY, "an 85% pattern should clear discovery"
    assert rec.conf_n == 0, "confirmation sample must start empty"
    assert rec.disc_n >= 100


def test_discovery_stats_are_never_quoted_after_promotion(reg):
    rng = np.random.default_rng(1)
    key = "s2"
    for i in range(400):
        if reg.record(key, "contagion", "D", f"b{i}", rng.random() < 0.85) is Stage.CONFIRMING:
            break
    rec = reg.get(key)
    assert rec.quoted_n == rec.conf_n == 0
    assert "not yet enough to confirm" in rec.render()


def test_only_confirmed_patterns_are_alertable(reg):
    rng = np.random.default_rng(2)
    for i in range(600):
        reg.record("s3", "contagion", "D", f"b{i}", rng.random() < 0.85)
    rec = reg.get("s3")
    assert rec.stage is Stage.CONFIRMED
    assert rec.alertable and rec.conf_n >= RegistryRules().confirm_n
    assert [r.pattern_key for r in reg.alertable()] == ["s3"]

    reg.record("mid", "contagion", "E", "b0", True)
    assert not reg.get("mid").alertable


# --------------------------------------------------- the headline result

def _campaign(tmp_path, run, true_p, rng, max_obs=1200):
    """Run one pattern to a terminal stage. Returns (stage, promotion_rate, quoted_rate)."""
    with PatternRegistry(tmp_path / f"r{run}.db") as reg:
        key, promoted_rate = "p", None
        for i in range(max_obs):
            prev = reg.get(key)
            stage = reg.record(key, "contagion", "S", f"b{i}", rng.random() < true_p)
            if stage is Stage.CONFIRMING and promoted_rate is None and prev and prev.disc_n:
                promoted_rate = prev.disc_hits / prev.disc_n
            if stage in (Stage.CONFIRMED, Stage.PRUNED):
                break
        rec = reg.get(key)
        return rec.stage, promoted_rate, (rec.hit_rate if rec.stage is Stage.CONFIRMED else None)


def test_confirmation_sample_is_an_unbiased_estimate(tmp_path):
    """The confirmation sample, taken over ALL promoted patterns, tracks truth.

    A pattern only crosses the discovery floor on a favourable run, so the rate
    measured at promotion is inflated. The fresh sample is not conditioned on
    that crossing.

    Note the measurement carefully: it is taken over every pattern that reached
    CONFIRMING, not only those that later passed. Filtering to the passers would
    reintroduce a selection — the confirmation gate is itself a filter — which
    is why `PatternRecord.render()` describes a CONFIRMED rate as unconditioned
    with respect to *discovery* and no more than that.
    """
    rng = np.random.default_rng(7)
    true_p, promo, fresh = 0.68, [], []
    rules = RegistryRules()

    for run in range(30):
        with PatternRegistry(tmp_path / f"u{run}.db") as reg:
            key, promoted_at = "p", None
            for i in range(1500):
                prev = reg.get(key)
                stage = reg.record(key, "contagion", "S", f"b{i}", rng.random() < true_p)
                if stage is Stage.CONFIRMING and promoted_at is None and prev and prev.disc_n:
                    promoted_at = prev.disc_hits / prev.disc_n
                rec = reg.get(key)
                if promoted_at is not None and rec.conf_n >= rules.confirm_n:
                    fresh.append(rec.conf_hits / rec.conf_n)   # every promoted pattern
                    promo.append(promoted_at)
                    break
                if stage is Stage.PRUNED:
                    break

    assert len(fresh) >= 12, f"only {len(fresh)}/30 reached a full confirmation sample"
    promo_mean, fresh_mean = float(np.mean(promo)), float(np.mean(fresh))

    assert promo_mean > true_p + 0.02, (
        f"promotion-time rate {promo_mean:.1%} should be inflated above {true_p:.0%}"
    )
    assert fresh_mean < promo_mean, "fresh sample must be less optimistic than discovery"
    assert abs(fresh_mean - true_p) < 0.05, (
        f"fresh sample {fresh_mean:.1%} drifted from true {true_p:.0%}"
    )


def test_a_62_percent_pattern_rarely_clears_a_65_percent_floor(tmp_path):
    """Documents a consequence the strategy write-up did not: the 0.65 discovery
    floor is not merely conservative, it filters out genuinely useful patterns.

    A true 62% edge is real and tradeable, and this pipeline will mostly discard
    it. That is a deliberate trade — false confidence costs more than a missed
    pattern — but it means "3-5 patterns at 65-75%" requires patterns whose TRUE
    rate is near 70%, not 62%.
    """
    rng = np.random.default_rng(21)
    confirmed = sum(
        _campaign(tmp_path, 1000 + run, 0.62, rng)[0] is Stage.CONFIRMED
        for run in range(40)
    )
    assert confirmed <= 10, f"{confirmed}/40 — floor is looser than documented"


def test_pure_noise_is_never_confirmed(tmp_path):
    """400 coin-flip patterns must produce no alertable pattern."""
    rng = np.random.default_rng(11)
    with PatternRegistry(tmp_path / "noise.db") as reg:
        for p in range(400):
            key = f"n{p}"
            for i in range(300):
                if reg.record(key, "contagion", "N", f"b{i}", rng.random() < 0.50) in (
                    Stage.CONFIRMED, Stage.PRUNED
                ):
                    break
        assert reg.alertable() == [], "noise reached an alertable state"


# ------------------------------------------------------------------ misc

def test_summary_is_explicit_when_nothing_is_ready(reg):
    reg.record("x", "news", "AAPL", "b0", True)
    assert "Nothing is alertable" in reg.summary()


def test_wilson_floors_match_the_documented_values():
    assert wilson_interval(75, 100, 0.90)[0] >= 0.65
    assert wilson_interval(70, 100, 0.90)[0] < 0.65
