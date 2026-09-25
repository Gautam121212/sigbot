"""The deep historical check reports completion, timing, and edge honestly."""
from __future__ import annotations

from sigbot.deep_check import describe, horizon_completion, model_health
from sigbot.shadow import ShadowLedger


def _seed(db):
    led = ShadowLedger(db)
    # 10 crypto (intra-day, ~2h), 6 win; 5 stocks (short-term, 24h), 3 win.
    for i in range(10):
        pid = led.record("crypto15m", f"C{i}", "BUY", 0.6, 0.02, 100.0, horizon_hours=2)
        led.resolve(pid, 101.0 if i < 6 else 99.0)
    for i in range(5):
        pid = led.record("stocks", f"S{i}", "BUY", 0.6, 0.02, 100.0, horizon_hours=24)
        led.resolve(pid, 101.0 if i < 3 else 99.0)


def test_model_health_reports_completion_and_edge(tmp_path):
    db = str(tmp_path / "s.db")
    _seed(db)
    health = {h.model: h for h in model_health(db)}
    assert health["crypto15m"].scored == 10 and health["crypto15m"].completion_pct == 100
    assert health["crypto15m"].hit_rate == 0.6      # 6/10
    assert "EDGE" in health["crypto15m"].verdict     # 60% > 52%
    assert health["stocks"].hit_rate == 0.6


def test_horizon_completion_groups_by_hold_time(tmp_path):
    db = str(tmp_path / "s.db")
    _seed(db)
    rows = {(m, h): (sc, tot) for m, h, sc, tot in horizon_completion(db)}
    assert rows[("crypto15m", "intra-day")] == (10, 10)
    assert rows[("stocks", "short-term")] == (5, 5)


def test_describe_names_every_aspect(tmp_path):
    db = str(tmp_path / "s.db")
    _seed(db)
    out = describe(db)
    assert "Completion, timing, and edge" in out
    assert "Per-horizon completion" in out
    assert "crypto15m" in out and "stocks" in out
