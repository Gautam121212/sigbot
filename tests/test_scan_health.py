"""System Health: durable per-family scan outcomes.

The acceptance is that a clean zero-setup scan, a scan failure, and a family
that never ran are three DISTINCT persisted states — not inferred from the
presence or absence of predictions.
"""
from __future__ import annotations

import time

from sigbot.scan_health import write_scan_health, read_scan_health


def test_three_states_are_distinct(tmp_path):
    p = tmp_path / "scan_health.json"
    write_scan_health({
        "crypto":   {"family": "crypto", "status": "SCAN_OK", "setups": 0, "scanned": 5},
        "ventures": {"family": "ventures", "status": "SCAN_OK", "setups": 2, "scanned": 40},
        "news":     {"family": "news", "status": "SCAN_FAILED", "setups": 0, "error": "Timeout"},
    }, path=p, build="abc1234")
    h = read_scan_health(p)
    assert h["build"] == "abc1234"
    fam = {f["family"]: f for f in h["families"]}
    # clean zero-setup scan
    assert fam["crypto"]["status"] == "SCAN_OK" and fam["crypto"]["setups"] == 0
    # ran and produced setups
    assert fam["ventures"]["setups"] == 2
    # failed, with the error preserved
    assert fam["news"]["status"] == "SCAN_FAILED" and fam["news"].get("error")
    # a family that never ran is simply absent — distinct from the above
    assert "stocks" not in fam


def test_absent_health_reads_as_none(tmp_path):
    assert read_scan_health(tmp_path / "nope.json") is None


def test_export_reads_scan_health_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_scan_health(
        {"crypto": {"family": "crypto", "status": "SCAN_OK", "setups": 0, "scanned": 5}},
        build="xyz")
    from sigbot.export_app import build_export
    d = build_export(str(tmp_path / "e.db"), str(tmp_path / "p.db"),
                     str(tmp_path / "w.db"))
    assert "health" in d
    assert d["health"]["build"] == "xyz"
    assert d["health"]["families"][0]["family"] == "crypto"


def test_note_scan_parses_summary_and_duration():
    from sigbot.live_handlers import RealSetupSources
    src = RealSetupSources(settings=object())
    src._note_scan("crypto", "SCAN_OK", 0, time.monotonic() - 1.2,
                   summary="crypto: scanned 5, 0 coiled-and-loaded this tick")
    rec = src.last_scans["crypto"]
    assert rec["status"] == "SCAN_OK" and rec["setups"] == 0
    assert rec["scanned"] == 5
    assert rec["duration_ms"] >= 1000
