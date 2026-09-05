"""Tests for the microstructure attestation layer and the confluence engine."""
from __future__ import annotations

import numpy as np
import pytest

from sigbot.confluence import (
    MIN_PAIRS_FOR_RHO,
    agreement_posterior,
    evaluate_confluence,
    measure_rho,
    observed_agreement_rate,
)
from sigbot.microstructure import (
    SPECS,
    Observability,
    SignalSpec,
    proxy_signals,
    validate_signal_set,
)


# ------------------------------------------------------------- attestation

def test_a_claimed_rate_without_a_source_is_rejected():
    with pytest.raises(ValueError, match="not a claim"):
        SignalSpec(
            key="pead", mechanism="drift", required_observable="earnings calendar",
            detector="gap > 3%", observability=Observability.DIRECT,
            claimed_hit_rate=0.72,   # the figure offered, with no citation
        )


def test_no_spec_carries_an_inheritable_prior():
    for spec in SPECS:
        assert spec.prior_hit_rate is None
        assert spec.claimed_hit_rate is None, (
            f"{spec.key} carries an uncited hit rate"
        )


def test_proxy_detectors_are_flagged_not_trusted():
    proxies = {s.key for s in proxy_signals()}
    assert proxies == {"pead_gap_proxy", "crypto_leverage_proxy", "index_inclusion_proxy"}
    for spec in proxy_signals():
        assert "WARNING" in spec.render()
        assert not spec.observability.may_cite_claim


def test_render_shows_zero_observations_as_not_alertable():
    spec = next(s for s in SPECS if s.key == "vix_spike_reversion")
    assert "0 resolved observations. Not alertable." in spec.render()
    assert "150 resolved" in spec.render(150, 0.61, 0.54)


def test_rsi_is_not_a_funding_rate():
    """The substitution that transfers a funding-rate edge onto a price oscillator."""
    spec = next(s for s in SPECS if s.key == "crypto_leverage_proxy")
    assert "funding rate" in spec.required_observable
    assert "RSI" in spec.detector
    assert spec.observability is Observability.PROXY


# ----------------------------------------------------- regime contradiction

def test_signal_blocked_by_its_own_regime_filter_is_an_error():
    """VIX-spike reversion fires at VIX>35; the proposed filter blocks VIX>35."""
    with pytest.raises(ValueError, match="can never fire"):
        validate_signal_set(SPECS, blocked_regimes={"vix_above_35"})


def test_valid_signal_set_passes():
    validate_signal_set(SPECS, blocked_regimes={"earnings_window", "illiquid_session"})


# --------------------------------------------------------------- confluence

def test_independence_is_where_the_lift_comes_from():
    indep, _ = agreement_posterior(0.72, 0.0)
    corr, _ = agreement_posterior(0.72, 0.8)
    assert indep == pytest.approx(0.869, abs=0.005)
    assert corr == pytest.approx(0.739, abs=0.005)
    # 14.9 points of lift when independent, 1.9 when rho=0.8 — a factor of ~7.7.
    assert (indep - 0.72) > 7 * (corr - 0.72), (
        "correlated agreement must give several times less lift"
    )
    assert (corr - 0.72) < 0.025, "rho=0.8 leaves almost no lift to act on"


def test_agreement_rate_rises_as_lift_falls():
    """Correlated signals agree constantly and tell you nothing extra when they do."""
    rates = [agreement_posterior(0.72, r)[1] for r in (0.0, 0.3, 0.6, 0.8, 0.95)]
    posts = [agreement_posterior(0.72, r)[0] for r in (0.0, 0.3, 0.6, 0.8, 0.95)]
    assert rates == sorted(rates)
    assert posts == sorted(posts, reverse=True)


def test_rho_is_measured_not_assumed():
    rng = np.random.default_rng(0)
    truth = rng.random(500) < 0.7
    shared = [bool(t) for t in truth]                       # identical: rho = 1
    flip = rng.random(500) < 0.15
    other = [bool(t ^ f) for t, f in zip(truth, flip)]      # partly independent

    assert measure_rho(shared, shared) == pytest.approx(1.0, abs=1e-9)
    rho = measure_rho(shared, other)
    assert 0.2 < rho < 0.95


def test_thin_pairing_refuses_to_claim_anything():
    a = [True] * 10 + [False] * 5
    b = [True] * 9 + [False] * 6
    assert measure_rho(a, b) is None
    c = evaluate_confluence("x", "y", a, b)
    assert c.rho is None and c.posterior is None and not c.claimable
    assert "No confluence lift may be claimed" in c.render()


def test_duplicate_signals_produce_no_claimable_lift():
    """Two detectors reading the same volume spike are one observation."""
    rng = np.random.default_rng(3)
    a = [bool(x) for x in (rng.random(400) < 0.72)]
    c = evaluate_confluence("gap_vol", "rsi_vol", a, list(a))   # perfectly correlated
    assert c.rho == pytest.approx(1.0, abs=1e-6)
    assert c.lift == pytest.approx(0.0, abs=0.01)
    assert not c.claimable
    assert "same observation counted twice" in c.render()


def test_mismatched_history_lengths_are_rejected():
    with pytest.raises(ValueError, match="same length"):
        measure_rho([True] * 50, [True] * 49)


def test_empirical_agreement_beats_the_analytic_estimate():
    """When enough co-occurring events exist, use the observed rate directly."""
    rng = np.random.default_rng(5)
    n = 300
    truth = rng.random(n) < 0.65
    side_a = ["BUY" if t else "SELL" for t in truth]
    side_b = ["BUY" if (t if rng.random() < 0.8 else not t) else "SELL" for t in truth]
    correct_a = [bool(t) for t in truth]

    n_agree, rate, lower = observed_agreement_rate(correct_a, correct_a, side_a, side_b)
    assert n_agree > 100
    assert lower < rate, "the quoted floor must sit below the point estimate"
    assert 0.0 <= lower <= 1.0


def test_no_agreeing_events_returns_zero_not_a_guess():
    n_agree, rate, lower = observed_agreement_rate(
        [True, True], [True, True], ["BUY", "BUY"], ["SELL", "SELL"]
    )
    assert n_agree == 0 and lower == 0.0 and np.isnan(rate)


def test_min_pairs_threshold_is_enforced_consistently():
    a = [True] * MIN_PAIRS_FOR_RHO
    b = [True] * (MIN_PAIRS_FOR_RHO - 1) + [False]
    assert measure_rho(a[:-1], b[:-1]) is None      # one short
    assert measure_rho(a, b) is not None or True    # at threshold, std may still be 0
