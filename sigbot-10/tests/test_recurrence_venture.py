"""Tests for recurrence measurement and business opportunity scoring."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sigbot.providers.market import SyntheticNetworkProvider
from sigbot.recurrence import (
    Recurrence,
    news_sensitivity,
    recurrence,
    recurrence_table,
    sensitivity_ranking,
    volume_event_days,
)
from sigbot.venture import (
    PLAN_THRESHOLD,
    RUBRIC,
    OpportunityScore,
    build_plan,
    render_digest,
)


@pytest.fixture(scope="module")
def panel():
    return SyntheticNetworkProvider(
        anchors=["A0", "A1"], couplings={"D": ("A0", 0.40)},
        independents=[f"N{i}" for i in range(6)], n_days=3000, seed=5,
    )


# ------------------------------------------------------------- recurrence

def test_counts_a_planted_relationship(panel):
    r = panel.log_returns()
    res = recurrence(r["A0"], r["D"], "A0", "D", sigma=2.0)
    assert res is not None
    assert res.n_anchor_shocks >= 50
    assert res.follow_rate > res.base_rate + 0.10
    assert res.follow_lower > res.base_rate, "planted link must clear its base rate"
    assert res.trustworthy


def test_reports_no_lift_for_unrelated_series(panel):
    r = panel.log_returns()
    res = recurrence(r["A0"], r["N3"], "A0", "N3", sigma=2.0)
    assert res is not None
    assert abs(res.lift) < 0.15
    assert not res.trustworthy, "an unrelated pair must not be marked trustworthy"


def test_rate_and_count_are_consistent(panel):
    r = panel.log_returns()
    res = recurrence(r["A0"], r["D"], "A0", "D")
    assert res.n_followed <= res.n_anchor_shocks
    assert res.follow_rate == pytest.approx(res.n_followed / res.n_anchor_shocks)
    assert res.follow_lower <= res.follow_rate <= res.follow_upper


def test_frequency_and_expected_wait_agree(panel):
    r = panel.log_returns()
    res = recurrence(r["A0"], r["D"], "A0", "D")
    assert res.shocks_per_year > 0
    assert res.expected_days_to_next == pytest.approx(252.0 / res.shocks_per_year)
    assert 1 < res.shocks_per_year < 60, "2σ shocks should be a handful per year"


def test_render_names_the_actual_counts(panel):
    r = panel.log_returns()
    text = recurrence(r["A0"], r["D"], "A0", "D").render()
    assert "times out of" in text and "next one due in" in text


def test_decay_is_detected_and_warned():
    strong = Recurrence("X", "Y", 2.0, 1, 100, 60, 0.60, 0.52, 0.68, 0.50,
                        10.0, 25.0, 10.0, 0.01, -0.01, 0.03, 0.75, 0.45)
    assert strong.decaying and not strong.trustworthy
    assert "rate is falling over time" in strong.render()


def test_thin_history_returns_none():
    idx = pd.bdate_range("2024-01-01", periods=100)
    s = pd.Series(np.random.default_rng(0).normal(0, 0.01, 100), index=idx)
    assert recurrence(s, s, "a", "b") is None


def test_table_ranks_by_lift(panel):
    r = panel.log_returns()
    tbl = recurrence_table(r, ["A0", "A1"], ["D"] + [f"N{i}" for i in range(6)],
                           min_shocks=20)
    assert len(tbl) > 3
    assert list(tbl["lift"]) == sorted(tbl["lift"], reverse=True)
    assert tbl.iloc[0]["dependent"] == "D", "the planted pair should rank first"
    assert {"shocks", "followed", "days_to_next", "decaying"} <= set(tbl.columns)


# ------------------------------------------------------ news sensitivity

def test_volume_proxy_uses_only_past_information(panel):
    bars = panel.frames["A0"]
    ev = volume_event_days(bars)
    truncated = volume_event_days(bars.iloc[:1500])
    pd.testing.assert_series_equal(
        ev.iloc[:1500], truncated, check_names=False
    )


def test_sensitivity_measures_amplification(panel):
    bars = panel.frames["A0"].copy()
    r = np.log(bars["close"]).diff().dropna()
    # Manufacture event days that genuinely move more.
    ev = pd.Series(False, index=r.index)
    ev.iloc[::10] = True
    r = r.copy()
    r[ev] = r[ev] * 3.0
    s = news_sensitivity(r, ev, "A0")
    assert s is not None and s.amplification > 2.0
    assert "moves" in s.render()


def test_sensitivity_ranking_orders_by_amplification(panel):
    ranked = sensitivity_ranking(panel.frames)
    assert len(ranked) >= 3
    assert list(ranked["amplification"]) == sorted(ranked["amplification"], reverse=True)


# ---------------------------------------------------------------- venture

def _scores(**overrides) -> dict[str, float]:
    base = {k: 8.0 for k in RUBRIC}
    base.update(overrides)
    return base


def test_every_rubric_item_must_be_scored():
    partial = {k: 8.0 for k in list(RUBRIC)[:-2]}
    with pytest.raises(ValueError, match="silent 10"):
        OpportunityScore("t", "th", "trig", partial)


def test_out_of_range_scores_rejected():
    with pytest.raises(ValueError, match="out of range"):
        OpportunityScore("t", "th", "trig", _scores(distribution=11.0))


def test_weights_sum_to_one_hundred():
    assert sum(w for w, *_ in RUBRIC.values()) == pytest.approx(100.0)


def test_perfect_and_zero_scores_bound_the_scale():
    assert OpportunityScore("t", "th", "g", {k: 10.0 for k in RUBRIC}).total == 100.0
    assert OpportunityScore("t", "th", "g", {k: 0.0 for k in RUBRIC}).total == 0.0


def test_distribution_failure_sinks_a_strong_idea():
    """An idea can be exciting everywhere and still fail on reaching a buyer."""
    op = OpportunityScore("Cyber consulting", "th", "trig",
                          _scores(distribution=1.0, time_to_first_revenue=2.0))
    assert not op.deserves_plan
    top = [k for k, _ in op.weakest]
    assert "distribution" in top and "time_to_first_revenue" in top


def test_plan_only_for_scores_above_threshold():
    weak = OpportunityScore("weak", "th", "trig", _scores(demand_evidence=2.0,
                                                          distribution=2.0))
    assert weak.total < PLAN_THRESHOLD
    with pytest.raises(ValueError, match="below"):
        build_plan(weak)
    assert "held back by" in weak.brief()


def test_plan_contains_the_sections_that_matter():
    op = OpportunityScore("SOC2 readiness for Delhi SaaS",
                          "Mid-size firms need compliance help; few local providers",
                          "Three enterprise breach stories in one week",
                          _scores(demand_evidence=9.0, distribution=9.0),
                          sources=["Reuters 2026-08-20"])
    assert op.deserves_plan
    plan = build_plan(op, "solo operator, Delhi")
    for section in ("Who pays", "First 60 days", "Unit economics",
                    "Cash conversion", "Skills required", "most likely to kill",
                    "Regulatory", "pitch"):
        assert section in plan
    assert "Kill criterion" in plan
    assert "Reuters 2026-08-20" in plan
    assert "TAM" not in plan, "market size slides are not what kills small ventures"


def test_plan_names_the_specific_weaknesses():
    op = OpportunityScore("t", "th", "trig", _scores(durability=1.0, competition_density=3.0))
    if op.deserves_plan:
        plan = build_plan(op)
        assert "Durability" in plan or "Competition Density" in plan


def test_digest_develops_strong_and_lists_weak():
    strong = OpportunityScore("Strong", "th", "trig", _scores(demand_evidence=10.0,
                                                              distribution=10.0))
    weak = OpportunityScore("Weak", "th", "trig", _scores(demand_evidence=1.0,
                                                          distribution=1.0,
                                                          skill_fit=2.0))
    text = render_digest([strong, weak], "Delhi solo operator")
    assert "First 60 days" in text
    assert "Below 80" in text
    assert "Weak" in text
    assert text.count("Unit economics") == 1, "only the strong idea gets a full plan"


def test_empty_digest_is_explicit():
    assert "No business opportunities" in render_digest([])
