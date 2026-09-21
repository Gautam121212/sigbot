"""The promotion ladder: evidence up, automatic demotion down, never execution."""
from __future__ import annotations

from sigbot.promotion import (
    FULL, LIMITED, LIVE_EXECUTION_ENABLED, PAPER, PILOT, Evidence, evaluate, t_stat,
)


def _ev(**kw):
    base = dict(hist_net_month=0.012, index_month=0.010, oos_net_month=0.006,
                # A genuinely strong record: +0.4 R a trade over 150 trades.
                paper_r=[0.6, -1.0, 1.2, 0.8, 0.4] * 30, paper_months=[0.015] * 8,
                paper_drawdown=0.06, review_drifts=0)
    base.update(kw)
    return Evidence(**base)


def test_live_execution_is_off_and_is_a_constant():
    """Real trading must be a deliberate human change to code, never something
    a passing test or a good month can switch on."""
    import inspect

    import sigbot.promotion as promo
    assert LIVE_EXECUTION_ENABLED is False
    src = inspect.getsource(promo)
    assert "LIVE_EXECUTION_ENABLED = False" in src
    for broker in ("place_order", "submit_order", "create_order", "requests.post"):
        assert broker not in src


def test_todays_evidence_keeps_it_on_paper():
    """Fair history trailed the index and unseen years were flat."""
    v = evaluate(_ev(hist_net_month=0.0054, oos_net_month=0.0001,
                     paper_r=[], paper_months=[-0.0006]))
    assert v.stage == PAPER and not v.eligible
    failed = {c.name for c in v.criteria if not c.passed}
    assert "Fair history beats holding the index" in failed
    assert "Unseen years were profitable after costs" in failed


def test_every_criterion_must_pass_not_most():
    strong = evaluate(_ev())
    assert strong.eligible and strong.next_stage == PILOT
    one_short = evaluate(_ev(review_drifts=1))
    assert not one_short.eligible


def test_luck_is_not_evidence():
    """A handful of good trades has a high average and a low t-statistic."""
    assert t_stat([2.0, 3.0]) < 2.0 or len([2.0, 3.0]) < 120
    v = evaluate(_ev(paper_r=[1.0, 1.2, 0.9]))
    assert not v.eligible


def test_a_bad_live_month_demotes_before_anything_else():
    v = evaluate(_ev(stage=LIMITED, months_at_stage=4, live_months=[0.01, -0.20]),
                 worst_hist_month=-0.12)
    assert v.demote and v.stage == PILOT
    assert "worse than the worst historical month" in v.demote_reason


def test_drift_demotes_a_live_stage():
    v = evaluate(_ev(stage=PILOT, live_months=[0.01], review_drifts=2))
    assert v.demote and v.stage == PAPER


def test_live_steps_need_time_real_results_and_real_costs():
    early = evaluate(_ev(stage=PILOT, months_at_stage=1, live_months=[0.01],
                         slippage_ratio=1.1))
    assert not early.eligible
    ready = evaluate(_ev(stage=PILOT, months_at_stage=3, live_months=[0.012] * 3,
                         slippage_ratio=1.2))
    assert ready.eligible and ready.next_stage == LIMITED
    costly = evaluate(_ev(stage=PILOT, months_at_stage=3, live_months=[0.012] * 3,
                          slippage_ratio=2.4))
    assert not costly.eligible, "real costs far above the model"


def test_full_is_the_top_but_still_watched():
    v = evaluate(_ev(stage=FULL, live_months=[0.01]))
    assert v.next_stage is None and not v.demote


def test_the_real_evidence_runs_end_to_end():
    from sigbot.runner import gather_promotion_evidence

    ev = gather_promotion_evidence()
    assert evaluate(ev).stage == PAPER



def test_a_small_edge_cannot_be_proven_in_any_reasonable_time():
    """Sigbot's historical edge is about +0.04 R a trade with a spread near
    1 R. Reaching the t >= 2 bar needs roughly (2 / 0.04)^2 = 2,500 trades —
    about 17 years at twelve a month. Waiting will not promote an edge that
    small; only a larger one can clear the bar in reasonable time. This test
    records that arithmetic so it is never mistaken for a matter of patience."""
    from sigbot.promotion import MIN_T_STAT

    edge, spread = 0.04, 1.0
    trades_needed = (MIN_T_STAT * spread / edge) ** 2
    assert trades_needed > 2000
    assert trades_needed / 12 / 12 > 15, "years at twelve trades a month"

    # A realistic +0.08 R record of 150 trades is still not proof.
    modest = evaluate(_ev(paper_r=[0.3, -1.0, 0.8, 0.5, -0.2] * 30))
    assert not modest.eligible
