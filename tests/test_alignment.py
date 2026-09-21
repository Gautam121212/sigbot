"""The monthly review must be able to say DRIFT, or it is decoration.

Every check here is tested in both directions: a disciplined record passes,
and the specific failure that check exists for makes it fire.
"""
from __future__ import annotations

from sigbot.alignment import (
    DRIFT, EARLY, PASS, check_both_schools, check_losses_are_cut,
    check_selectivity, check_streak_discipline, check_winners_run,
    describe, record_history, review_setups,
)


def _t(r, setup="oversold-money-holding", taken=True):
    return {"r": r, "hit": r > 0, "setup": setup, "taken": taken}


def test_too_few_trades_is_too_early_never_a_pass():
    """For the first months TOO EARLY is the honest answer, and must never be
    read as PASS."""
    assert check_losses_are_cut([_t(-1.0)] * 5).verdict == EARLY
    assert check_winners_run([_t(1.0)] * 5).verdict == EARLY


def test_stops_that_hold_pass_and_losses_that_run_drift():
    assert check_losses_are_cut([_t(-1.0)] * 40).verdict == PASS
    drift = check_losses_are_cut([_t(-2.5)] * 40)
    assert drift.verdict == DRIFT and "B84" in drift.note


def test_small_wins_against_large_losses_drift():
    good = [_t(1.5)] * 20 + [_t(-1.0)] * 20
    bad = [_t(0.4)] * 30 + [_t(-1.0)] * 20
    assert check_winners_run(good).verdict == PASS
    assert check_winners_run(bad).verdict == DRIFT


def test_recording_most_of_what_it_sees_drifts():
    assert check_selectivity(10_000, 300).verdict == PASS
    assert check_selectivity(10_000, 6_000).verdict == DRIFT
    assert check_selectivity(100, 5).verdict == EARLY


def test_trading_through_a_losing_streak_drifts():
    # Disciplined: after four losses the desk stands aside, keeps recording,
    # and resumes only once a REFUSED signal has won on paper.
    ok = ([_t(-1.0)] * 4 + [_t(-1.0, taken=False)] * 3
          + [_t(1.0, taken=False)] + [_t(1.0)] * 30)
    breach = [_t(-1.0)] * 4 + [_t(-1.0, taken=True)] * 3 + [_t(1.0)] * 30
    assert check_streak_discipline(ok, 4).verdict == PASS
    bad = check_streak_discipline(breach, 4)
    # Three losses and the first win, all taken while the streak stood.
    assert bad.verdict == DRIFT and "4 position" in bad.note


def test_one_school_alone_drifts():
    both = ([_t(1.0, "momentum-breakout")] * 20
            + [_t(1.0, "oversold-money-holding")] * 20)
    one = [_t(1.0, "oversold-money-holding")] * 40
    assert check_both_schools(both).verdict == PASS
    assert check_both_schools(one).verdict == DRIFT


def test_a_decaying_setup_is_flagged_not_silently_averaged_away():
    trades = ([_t(-0.3, "momentum-breakout")] * 40
              + [_t(0.8, "oversold-money-holding")] * 40)
    reviews = {r.setup: r for r in review_setups(trades)}
    assert "DECAY" in reviews["momentum-breakout"].recommendation
    assert "DECAY" not in reviews["oversold-money-holding"].recommendation


def test_a_strong_risky_setup_is_recommended_for_review_not_promoted():
    """Promotion is a recommendation. Nothing changes a rule by itself."""
    from sigbot.scan import CANDIDATES, RISKY, tier_of

    trades = [_t(0.5, "momentum-breakout")] * 130
    rec = {r.setup: r for r in review_setups(trades)}["momentum-breakout"]
    assert "REVIEW FOR PROMOTION" in rec.recommendation
    mom = next(c for c in CANDIDATES if c.name == "momentum-breakout")
    assert tier_of(mom) == RISKY, "the review must not have changed the tier"


def test_history_is_kept_and_bounded(tmp_path):
    import json

    path = tmp_path / "h.json"
    checks = [check_selectivity(100, 5)]
    for _ in range(60):
        record_history(checks, [], path=str(path))
    history = json.loads(path.read_text())
    assert len(history) == 52, "a year of weekly reviews, not unbounded"


def test_the_report_says_recommendations_only():
    assert "Recommendations only" in describe([check_selectivity(1, 0)], [])


def test_each_stocks_trade_records_its_setup():
    """Without the setup name the review can only judge the model as a whole,
    and a decaying setup would be averaged away by one that works."""
    import inspect

    import sigbot.runner as runner
    src = inspect.getsource(runner.run_stocks)
    assert '"setup": hit.candidate.name' in src



def test_the_pause_lifts_through_refused_signals_or_it_would_never_lift(tmp_path):
    """A streak only resets on a closed win, and refused trades are never
    taken. It lifts because refused signals are still RECORDED and SCORED: the
    desk keeps a shadow record while standing aside and resumes when the setup
    works again. If the streak ever counted only taken trades, the first bad
    week would lock the system out permanently."""
    import json

    from sigbot.shadow import ShadowLedger

    ledger = ShadowLedger(str(tmp_path / "s.db"))
    for _ in range(4):
        pid = ledger.record("stocks", "X", "BUY", 0.7, 0.05, 100.0,
                            payload=json.dumps({"taken": True}))
        ledger.resolve(pid, 90.0)
    assert ledger.current_loss_streak("stocks") == 4

    pid = ledger.record("stocks", "Y", "BUY", 0.7, 0.05, 100.0,
                        payload=json.dumps({"taken": False}))
    ledger.resolve(pid, 110.0)
    assert ledger.current_loss_streak("stocks") == 0, (
        "a refused signal that would have won must end the pause")
