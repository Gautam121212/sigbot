"""Prediction admission — look-ahead guard + per-model dedup."""
from datetime import datetime, timedelta, timezone

from sigbot.prediction_admission import (
    AdmissionVerdict, Model, PredictionClaim, PredictionTimestamps, admit)

BASE = datetime(2026, 10, 5, 3, 15, tzinfo=timezone.utc)


def _claim(model=Model.STOCKS, symbol="DEVYANI.NS", as_of_h=0, created_h=0,
           start_h=6, end_h=30, **kw):
    return PredictionClaim(
        model=model, symbol=symbol,
        as_of=BASE + timedelta(hours=as_of_h),
        created_at=BASE + timedelta(hours=created_h),
        outcome_start=BASE + timedelta(hours=start_h),
        outcome_end=BASE + timedelta(hours=end_h),
        horizon=kw.get("horizon", "7d"),
        signal_instance=kw.get("signal_instance", ""),
        event_id=kw.get("event_id", ""),
        thesis_id=kw.get("thesis_id", ""),
        opportunity_id=kw.get("opportunity_id", ""))


# ── invariant 1: look-ahead guard ───────────────────────────────────────────
def test_valid_overnight_prediction_admitted():
    assert admit(_claim(), set()).verdict == AdmissionVerdict.ADMIT


def test_info_after_window_open_rejected():
    """as_of at hour 10, window opened at hour 6 -> could see the move -> reject."""
    r = admit(_claim(as_of_h=10, created_h=10), set())
    assert r.verdict == AdmissionVerdict.REJECT_LOOKAHEAD


def test_created_after_window_open_rejected():
    r = admit(_claim(as_of_h=0, created_h=7), set())   # created after open (6h)
    assert r.verdict == AdmissionVerdict.REJECT_LOOKAHEAD


def test_as_of_after_created_rejected():
    """Information can't be newer than the decision that used it."""
    r = admit(_claim(as_of_h=2, created_h=1), set())
    assert r.verdict == AdmissionVerdict.REJECT_LOOKAHEAD


def test_as_of_exactly_at_window_open_rejected():
    """Boundary: as_of == outcome_start is NOT strictly before -> reject."""
    r = admit(_claim(as_of_h=6, created_h=6, start_h=6), set())
    assert r.verdict == AdmissionVerdict.REJECT_LOOKAHEAD


# ── invariant: window shape ─────────────────────────────────────────────────
def test_zero_length_window_rejected():
    r = admit(_claim(start_h=6, end_h=6), set())
    assert r.verdict == AdmissionVerdict.REJECT_BAD_WINDOW


def test_inverted_window_rejected():
    r = admit(_claim(start_h=30, end_h=6), set())
    assert r.verdict == AdmissionVerdict.REJECT_BAD_WINDOW


# ── invariant 2: per-model dedup ────────────────────────────────────────────
def test_stocks_duplicate_symbol_rejected():
    c = _claim(model=Model.STOCKS, symbol="DEVYANI.NS", horizon="7d")
    assert admit(c, {"stocks|DEVYANI.NS|7d"}).verdict == AdmissionVerdict.REJECT_DUPLICATE


def test_stocks_different_horizon_not_duplicate():
    c = _claim(model=Model.STOCKS, symbol="DEVYANI.NS", horizon="30d")
    assert admit(c, {"stocks|DEVYANI.NS|7d"}).verdict == AdmissionVerdict.ADMIT


def test_news_distinct_events_both_admit():
    """News fires twice on two different events — not a duplicate."""
    c1 = _claim(model=Model.NEWS, symbol="NVDA", start_h=1, end_h=25,
                horizon="1d", event_id="EV-1")
    c2 = _claim(model=Model.NEWS, symbol="NVDA", as_of_h=4, created_h=4,
                start_h=5, end_h=29, horizon="1d", event_id="EV-2")
    open_keys = {c1.dedup_key()}
    assert admit(c2, open_keys).verdict == AdmissionVerdict.ADMIT


def test_news_same_event_rejected():
    c1 = _claim(model=Model.NEWS, symbol="NVDA", start_h=1, end_h=25,
                horizon="1d", event_id="EV-1")
    assert admit(c1, {c1.dedup_key()}).verdict == AdmissionVerdict.REJECT_DUPLICATE


def test_ventures_dedup_by_thesis():
    c = _claim(model=Model.VENTURES, symbol="X", thesis_id="TH-900")
    assert c.dedup_key() == "ventures|TH-900"
    assert admit(c, {"ventures|TH-900"}).verdict == AdmissionVerdict.REJECT_DUPLICATE


def test_ideas_dedup_by_opportunity():
    c = _claim(model=Model.IDEAS, symbol="X", opportunity_id="OP-7")
    assert c.dedup_key() == "ideas|OP-7"


def test_crypto_dedup_includes_signal_instance():
    c = _claim(model=Model.CRYPTO, symbol="BTC-USD", start_h=1, end_h=4,
               horizon="3h", signal_instance="run-42")
    assert "run-42" in c.dedup_key()


# ── check order: integrity before dedup ─────────────────────────────────────
def test_lookahead_checked_before_dedup():
    """A look-ahead prediction is rejected for look-ahead even if also a dup."""
    c = _claim(as_of_h=10, created_h=10)
    r = admit(c, {c.dedup_key()})
    assert r.verdict == AdmissionVerdict.REJECT_LOOKAHEAD


# ── timestamp chain stored ──────────────────────────────────────────────────
def test_timestamps_from_claim():
    c = _claim()
    ts = PredictionTimestamps.from_claim(c)
    assert ts.as_of == c.as_of.isoformat()
    assert ts.outcome_start == c.outcome_start.isoformat()
    assert ts.resolution_time == ""      # empty while open


# ── admitted result exposes the key for the open set ────────────────────────
def test_admit_returns_key_for_tracking():
    c = _claim()
    r = admit(c, set())
    assert r.admitted()
    assert r.dedup_key == "stocks|DEVYANI.NS|7d"


# ── the gate wired into ShadowLedger.record (live runners use gate=True) ────
def test_record_gate_blocks_duplicate():
    import os
    import tempfile
    from sigbot.shadow import ShadowLedger
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        L = ShadowLedger(path)
        assert L.record("stocks", "AAPL", "BUY", 0.6, 0.05, 100.0, 24,
                        gate=True) > 0
        assert L.record("stocks", "AAPL", "BUY", 0.6, 0.05, 100.0, 24,
                        gate=True) == 0        # duplicate refused
    finally:
        os.unlink(path)


def test_record_gate_blocks_future_as_of():
    import os
    import tempfile
    from datetime import datetime, timedelta, timezone
    from sigbot.shadow import ShadowLedger
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        L = ShadowLedger(path)
        future = datetime.now(timezone.utc) + timedelta(hours=5)
        assert L.record("stocks", "MSFT", "BUY", 0.6, 0.05, 100.0, 24,
                        as_of=future, gate=True) == 0    # look-ahead refused
    finally:
        os.unlink(path)


def test_record_gate_blocks_nonpositive_horizon():
    import os
    import tempfile
    from sigbot.shadow import ShadowLedger
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        L = ShadowLedger(path)
        assert L.record("stocks", "GOOG", "BUY", 0.6, 0.05, 100.0, 0,
                        gate=True) == 0
    finally:
        os.unlink(path)


def test_record_without_gate_is_pure_storage():
    """Default gate=False keeps record() a storage primitive for fixtures."""
    import os
    import tempfile
    from sigbot.shadow import ShadowLedger
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        L = ShadowLedger(path)
        assert L.record("daily", "NVDA", "BUY", 0.7, 0.01, 100.0) > 0
        assert L.record("daily", "NVDA", "BUY", 0.7, 0.01, 100.0) > 0  # dup ok
    finally:
        os.unlink(path)
