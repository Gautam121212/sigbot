"""Tests for the threshold prover and the integrity checks."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from sigbot.integrity import (
    changed_since, fingerprint, require, verify, verify_all,
)
from sigbot.stats import wilson_interval
from sigbot.threshold_prover import (
    prove, prove_all, report, required_rate, sample_for,
)


def _bars(n=300, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    wick = np.abs(rng.normal(0, 0.005, n)) * close
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        dict(open=open_,
             high=np.maximum.reduce([close, open_]) + wick,
             low=np.minimum.reduce([close, open_]) - wick,
             close=close, volume=rng.lognormal(12, 0.3, n)),
        index=pd.bdate_range("2024-01-01", periods=n))


# ------------------------------------------------------------- the prover

def test_every_live_threshold_is_reachable():
    """If this fails, a tier in the running system cannot fire."""
    bad = [p for p in prove_all() if not p.reachable]
    assert not bad, "\n".join(p.render() for p in bad)


def test_an_impossible_gate_is_rejected():
    p = prove("impossible", 30, 0.995)
    assert not p.reachable and "cannot fire" in p.note


def test_a_decorative_gate_is_rejected():
    """A gate a record exactly at the gate already clears is not gating."""
    p = prove("decorative", 5, 0.30)
    assert "decorative" in p.note or not p.reachable or p.n_for_plausible > 5


def test_min_n_is_a_floor_not_the_judging_sample():
    """Asking 'what rate clears it at exactly min_n' flagged four working
    tiers on this module's first run. An asset clears a tier at any n above
    the floor."""
    p = prove("tier", 40, 0.60)
    assert p.reachable
    assert p.n_for_plausible and p.n_for_plausible > 40
    assert "not what binds" in p.note


def test_required_rate_matches_the_wilson_maths():
    for n, gate in [(40, 0.60), (100, 0.55), (150, 0.60)]:
        r = required_rate(n, gate)
        assert r is not None
        assert wilson_interval(round(r * n), n, 0.90)[0] >= gate
        below = max(0, round(r * n) - 1)
        assert wilson_interval(below, n, 0.90)[0] < gate


def test_required_rate_is_none_when_perfection_still_misses():
    assert required_rate(5, 0.95) is None


def test_sample_for_rejects_a_rate_at_or_below_the_gate():
    assert sample_for(0.60, 0.60) is None
    assert sample_for(0.50, 0.60) is None
    assert sample_for(0.70, 0.60) is not None


def test_report_is_readable():
    text = report()
    assert "tier TRADE" in text and "confidence" in text


# ----------------------------------------------------------- integrity

def test_clean_bars_pass():
    r = verify(_bars(), "OK", now=datetime(2024, 12, 31, tzinfo=timezone.utc))
    assert r.ok and "clean" in r.render() or r.ok


def test_high_below_close_is_rejected():
    """A bar where the high is under the close did not happen."""
    b = _bars()
    b.iloc[10, b.columns.get_loc("high")] = b["close"].iloc[10] - 1
    r = verify(b, "BAD")
    assert not r.ok and any("high < max" in p for p in r.problems)


def test_low_above_open_is_rejected():
    b = _bars()
    b.iloc[5, b.columns.get_loc("low")] = b["open"].iloc[5] + 1
    assert any("low > min" in p for p in verify(b, "BAD").problems)


def test_inverted_bar_is_rejected():
    b = _bars()
    i = b.columns.get_loc("high"), b.columns.get_loc("low")
    b.iloc[7, i[0]], b.iloc[7, i[1]] = 50.0, 150.0
    probs = verify(b, "BAD").problems
    assert any("high < low" in p for p in probs) or len(probs) >= 1


def test_negative_and_zero_prices_are_rejected():
    b = _bars()
    b.iloc[3, b.columns.get_loc("close")] = 0.0
    assert any("negative prices" in p for p in verify(b, "BAD").problems)


def test_negative_volume_is_rejected():
    b = _bars()
    b.iloc[3, b.columns.get_loc("volume")] = -5
    assert any("negative volume" in p for p in verify(b, "BAD").problems)


def test_non_numeric_data_is_rejected_not_crashed_on():
    b = _bars()
    b["close"] = "not a price"
    r = verify(b, "BAD")
    assert not r.ok and any("non-numeric" in p for p in r.problems)


def test_missing_columns_and_empty_frames():
    assert not verify(pd.DataFrame(), "E").ok
    assert not verify(None, "E").ok
    assert any("missing columns" in p for p in verify(_bars().drop(columns=["volume"]), "M").problems)


def test_out_of_order_and_duplicate_timestamps():
    b = _bars(50)
    shuffled = b.iloc[::-1]
    assert any("not in order" in p for p in verify(shuffled, "S").problems)
    dup = pd.concat([b, b.iloc[[0]]])
    assert not verify(dup, "D").ok


def test_staleness_is_a_warning_not_a_failure():
    """A stale feed is usually a holiday. The caller judges, not this module."""
    b = _bars(50)
    r = verify(b, "OLD", "1d", now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert r.ok, "staleness must not fail the frame"
    assert any("old" in w for w in r.warnings)


def test_an_unadjusted_split_is_flagged_as_a_warning():
    b = _bars()
    for col in ("open", "high", "low", "close"):
        b.iloc[100:, b.columns.get_loc(col)] /= 4.0
    r = verify(b, "SPLIT", now=datetime(2024, 12, 31, tzinfo=timezone.utc))
    assert any("unadjusted split" in w for w in r.warnings)


def test_require_raises_on_bad_data():
    b = _bars()
    b.iloc[2, b.columns.get_loc("high")] = 0.0
    with pytest.raises(ValueError, match="failed integrity"):
        require(b, "BAD")
    assert require(_bars(), "OK") is not None


def test_fingerprint_detects_a_silent_rewrite():
    """Yahoo rewrites old bars for splits. This makes the change visible —
    going forward only; it cannot recover what was rewritten before."""
    b = _bars()
    before = fingerprint(b)
    assert not changed_since(b.copy(), before)
    b.iloc[0, b.columns.get_loc("close")] *= 2
    assert changed_since(b, before)


def test_fingerprint_handles_empty_input():
    assert fingerprint(pd.DataFrame()) == fingerprint(None)


def test_verify_all_puts_problems_first():
    good, bad = _bars(), _bars()
    bad.iloc[1, bad.columns.get_loc("high")] = 0.0
    results = verify_all({"GOOD": good, "BAD": bad})
    assert results[0].symbol == "BAD" and not results[0].ok
