"""Tests for Model C (contagion) and Model D (opportunities).

The two that matter are `test_screener_finds_planted_link` and
`test_screener_finds_nothing_in_noise`. A screener that fails either is not a
measuring instrument. Running only the null test is a common half-measure: a
screener that returns nothing always passes it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from sigbot.contagion import (
    ContagionGates,
    benjamini_hochberg,
    build_network,
    event_response,
    gate,
    ols_hc1,
)
from sigbot.opportunities import OpportunityModel, ThesisCard, render_digest
from sigbot.providers.market import SyntheticNetworkProvider
from sigbot.types import Article

ANCHORS = [f"A{i}" for i in range(10)]
NOISE = [f"N{i}" for i in range(48)]


@pytest.fixture(scope="module")
def coupled():
    return SyntheticNetworkProvider(
        anchors=ANCHORS,
        couplings={"D": ("A0", 0.35), "E": ("A1", 0.20)},
        independents=NOISE, n_days=3000, seed=5,
    )


@pytest.fixture(scope="module")
def uncoupled():
    return SyntheticNetworkProvider(
        anchors=ANCHORS, couplings={},
        independents=[f"N{i}" for i in range(50)], n_days=3000, seed=9,
    )


# ------------------------------------------------------------------ screener

def test_screener_finds_planted_link(coupled):
    """Power: a real lag-1 relationship must survive FDR control."""
    links = build_network(coupled.log_returns(), ANCHORS, ["D", "E"] + NOISE, alpha=0.10)
    found = {(lk.anchor, lk.dependent) for lk in links if lk.tradeable}
    assert ("A0", "D") in found
    assert ("A1", "E") in found

    d = next(lk for lk in links if (lk.anchor, lk.dependent) == ("A0", "D"))
    assert d.beta_lagged == pytest.approx(0.35, abs=0.06), "recovered beta must be close"
    assert abs(d.beta_contemp) < 0.05, "planted link is lagged, not contemporaneous"


def test_screener_finds_nothing_in_noise(uncoupled):
    """Null: independent series must yield no surviving links."""
    cands = [f"N{i}" for i in range(50)]
    links = build_network(uncoupled.log_returns(), ANCHORS, cands, alpha=0.10)
    survivors = [lk for lk in links if lk.tradeable]
    assert len(links) > 400, "screen should actually test many pairs"
    assert len(survivors) == 0, f"{len(survivors)} spurious links survived FDR"


def test_fdr_is_doing_real_work(uncoupled):
    """Without correction this screen would report dozens of false links."""
    cands = [f"N{i}" for i in range(50)]
    links = build_network(uncoupled.log_returns(), ANCHORS, cands, alpha=0.10)
    naive = sum(1 for lk in links if lk.p_lagged < 0.05)
    corrected = sum(1 for lk in links if lk.tradeable)
    assert naive >= 15, "expected ~5% of pairs to be spuriously significant"
    assert corrected < naive / 5


def test_benjamini_hochberg_properties():
    q = benjamini_hochberg([0.001, 0.02, 0.4, 0.9])
    assert all(a <= b + 1e-12 for a, b in zip(q, q[1:])), "q-values must be monotone"
    assert all(qi >= pi for qi, pi in zip(q, [0.001, 0.02, 0.4, 0.9]))
    assert benjamini_hochberg([]) == []


def test_ols_recovers_known_slope():
    rng = np.random.default_rng(1)
    x = rng.normal(size=4000)
    y = 0.7 * x + rng.normal(scale=0.5, size=4000)
    beta, se, t, n = ols_hc1(x, y)
    assert beta == pytest.approx(0.7, abs=0.03)
    assert t > 20 and n == 4000


def test_ols_refuses_tiny_samples():
    beta, se, t, n = ols_hc1(np.arange(10.0), np.arange(10.0))
    assert np.isnan(beta) and n == 10


# -------------------------------------------------------------- event study

def test_event_response_uses_trailing_volatility_only(coupled):
    r = coupled.log_returns()
    resp = event_response(r["A0"], r["D"], "A0", "D", sigma=2.0)
    assert resp is not None
    assert resp.n_events > 50
    assert resp.hit_rate > resp.base_hit_rate, "planted link must beat its base rate"
    assert resp.q10 < resp.mean_response < resp.q90


def test_event_response_returns_none_on_short_history(coupled):
    r = coupled.log_returns()
    assert event_response(r["A0"].iloc[:100], r["D"].iloc[:100], "A0", "D") is None


def test_gates_block_thin_event_samples(coupled):
    r = coupled.log_returns()
    links = build_network(r, ["A0"], ["D"], alpha=0.10)
    resp = event_response(r["A0"], r["D"], "A0", "D", sigma=2.0)
    ok, blocked = gate(resp, links[0], ContagionGates(min_events=100_000))
    assert not ok and any("historical shocks" in b for b in blocked)


# ------------------------------------------------------------ opportunities

def _art(title: str, summary: str, source: str, days: int = 0) -> Article:
    now = datetime(2026, 3, 1, tzinfo=timezone.utc) - timedelta(days=days)
    return Article(title[:8], title, summary, "u", source, now, now)


def test_opportunity_model_never_emits_a_score():
    arts = [
        _art("Acme Robotics files to go public on Nasdaq",
             "The company filed an S-1 seeking to raise $800m.", "Reuters"),
        _art("Dubai property prices fall as regional conflict escalates",
             "Asking prices in prime districts are down sharply.", "Reuters"),
        _art("Local blog says buy everything now", "trust me", "randomblog.xyz"),
    ]
    cards = OpportunityModel().scan(arts)
    cats = {c.category for c in cards}
    assert cats == {"ipo", "macro"}, "low-quality source must be dropped"

    text = render_digest(cards, "jurisdiction note here")
    assert "Confidence: NONE" in text
    assert "jurisdiction note here" in text
    # No percentage-style confidence anywhere in the output.
    assert "confidence - " not in text.lower()
    for c in cards:
        assert not hasattr(c, "score")
        assert c.must_be_true and c.would_falsify and c.unobservable


def test_thesis_card_forces_disconfirmation():
    card = ThesisCard("macro", "X", "claim", "mechanism", [])
    rendered = card.render()
    assert "Confidence: NONE" in rendered


def test_empty_digest_is_explicit():
    assert "nothing matched" in render_digest([])
