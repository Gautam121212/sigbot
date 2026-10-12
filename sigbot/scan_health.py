"""Durable per-family scan outcomes for the System Health page.

The OperatingLoop pre-scans ventures, news and crypto every tick, but their
outcomes were only printed to the tick log and counted in memory. This module
persists the last tick's outcome per family so the dashboard can tell apart:
  - a successful scan that found zero setups,
  - a scan that FAILED (with the error), and
  - a family that never ran (absent from the file),
instead of inferring any of them from the presence or absence of predictions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def write_scan_health(scans: dict, path: str | Path = "scan_health.json",
                      build: str | None = None) -> Path:
    """Persist the per-family scan records captured during a tick.

    `scans` is RealSetupSources.last_scans: {family: {status, setups, ...}}.
    """
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build": build,
        "families": [scans[k] for k in sorted(scans)] if scans else [],
    }
    p = Path(path)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def read_scan_health(path: str | Path = "scan_health.json") -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  # handled: absent/unreadable health renders as "not yet recorded"
        return None
