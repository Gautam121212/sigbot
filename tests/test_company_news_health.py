"""Company Narrative Health — anti-lookahead guards + correction + neg-control."""
from datetime import datetime, timedelta, timezone

from sigbot.company_news_health import (
    Atom, CompanyNewsHealthResult, GdeltRecord, available_at,
    compute_snapshot, corrected_t_bar, evaluate_atom)


def _dt(*a):
    return datetime(*a, tzinfo=timezone.utc)


DECISION = _dt(2023, 6, 15, 3, 15)


def _rec(company="ACME", pub=None, proc=None, tone=0.0, domain="x.com",
         themes=("T",)):
    pub = pub or _dt(2023, 6, 14, 10, 0)
    proc = proc or (pub + timedelta(minutes=15))
    return GdeltRecord(company, pub, proc, tone, domain, themes)


# ── guarantee 1: publication AND processing time before decision ────────────
def test_available_excludes_future_publication():
    recs = [_rec(pub=_dt(2023, 6, 16, 8, 0))]      # published after
    assert available_at(recs, DECISION) == []


def test_available_excludes_late_processing():
    """Published before but PROCESSED after the decision = leak; must exclude."""
    recs = [_rec(pub=_dt(2023, 6, 15, 2, 0), proc=_dt(2023, 6, 15, 4, 0))]
    assert available_at(recs, DECISION) == []


def test_available_keeps_fully_prior_records():
    recs = [_rec(pub=_dt(2023, 6, 14, 10, 0), proc=_dt(2023, 6, 14, 10, 15))]
    assert len(available_at(recs, DECISION)) == 1


# ── guarantee 2: baseline strictly before recent window ─────────────────────
def test_baseline_does_not_straddle_recent():
    recs = [
        _rec(pub=_dt(2023, 6, 14), tone=1.0),       # recent (within 7d)
        _rec(pub=_dt(2023, 3, 1), tone=-1.0),       # baseline
    ]
    snap = compute_snapshot(recs, "ACME", DECISION, recent_days=7,
                            baseline_days=365)
    # trend = recent mean (1.0) - baseline mean (-1.0) = 2.0
    assert snap.sentiment_trend == 2.0


def test_snapshot_uses_only_available():
    recs = [
        _rec(pub=_dt(2023, 6, 14), tone=0.5),
        _rec(pub=_dt(2023, 6, 16), tone=5.0),       # future -> excluded
    ]
    snap = compute_snapshot(recs, "ACME", DECISION)
    assert snap.n_recent == 1                        # the future one ignored


# ── atoms are change-relative, not absolute ─────────────────────────────────
def test_sentiment_trend_is_change_not_level():
    # high absolute tone but NO change vs baseline -> trend ~0
    recs = [_rec(pub=_dt(2023, 6, 14), tone=0.9),
            _rec(pub=_dt(2023, 3, 1), tone=0.9)]
    snap = compute_snapshot(recs, "ACME", DECISION)
    assert abs(snap.sentiment_trend) < 0.01          # no trend despite +0.9 tone


def test_coverage_acceleration_computed():
    recs = [_rec(pub=_dt(2023, 6, 14)), _rec(pub=_dt(2023, 6, 13)),
            _rec(pub=_dt(2023, 3, 1))]
    snap = compute_snapshot(recs, "ACME", DECISION)
    assert snap.coverage_acceleration > 0            # recent burst vs baseline


# ── multiple-testing correction ─────────────────────────────────────────────
def test_corrected_bar_rises_with_cells():
    assert corrected_t_bar(1) < corrected_t_bar(18)
    assert corrected_t_bar(18) > 2.9                 # ~2.99 for 18 cells


# ── guarantee 3: negative control kills artifacts ───────────────────────────
def test_negative_control_rejects_artifact():
    """If a future-shifted narrative predicts just as well, it's an artifact."""
    bar = corrected_t_bar(18)
    r = evaluate_atom(Atom.SENTIMENT_TREND, 30, n_signals=400,
                      dev_separation=3.0, oos_separation=2.5, oos_mean=3.0,
                      oos_std=18, negative_control_separation=2.5, t_bar=bar)
    assert not r.survives


def test_clean_negative_control_allows_survivor():
    bar = corrected_t_bar(18)
    r = evaluate_atom(Atom.SENTIMENT_TREND, 30, n_signals=400,
                      dev_separation=3.5, oos_separation=2.8, oos_mean=3.0,
                      oos_std=18, negative_control_separation=0.1, t_bar=bar)
    assert r.survives


# ── survival requires dev AND oos AND correction AND clean control ──────────
def test_dev_only_does_not_survive():
    bar = corrected_t_bar(18)
    r = evaluate_atom(Atom.SENTIMENT_TREND, 30, n_signals=400,
                      dev_separation=3.0, oos_separation=-0.2, oos_mean=-0.2,
                      oos_std=18, negative_control_separation=0.1, t_bar=bar)
    assert not r.survives


def test_below_corrected_bar_does_not_survive():
    bar = corrected_t_bar(18)
    # t ~ 2.3, below the 2.99 bar
    r = evaluate_atom(Atom.SENTIMENT_TREND, 30, n_signals=400,
                      dev_separation=2.8, oos_separation=2.1, oos_mean=2.1,
                      oos_std=18, negative_control_separation=0.1, t_bar=bar)
    assert not r.survives


# ── the result never fabricates a verdict ───────────────────────────────────
def test_default_verdict_is_not_run():
    res = CompanyNewsHealthResult()
    assert res.verdict == "NOT_RUN"
    assert res.survivors() == []


# ── it's narrative, not "company health" ────────────────────────────────────
def test_describe_says_narrative_not_health():
    from sigbot.company_news_health import describe
    d = describe()
    assert "NARRATIVE" in d
    assert "private" in d and "operations" in d
    assert "NEVER fabricates a verdict" in d
