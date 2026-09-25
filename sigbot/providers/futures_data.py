"""Reader for the banked F&O data the recorders collect.

The recorders (recorders/*.py) run on the user's Mac and append live readings
to data/*.jsonl. This reads those files so the edge campaign can test on the
banked history. It reads only — it never fetches, so it works in any
environment including the sandbox.

Until the recorders have run for a while, these return empty, and the edge
tests that depend on them simply report "not enough history yet" rather than
inventing data.
"""
from __future__ import annotations

import json
from pathlib import Path


def _read_jsonl(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # skip a torn last line mid-write
    return out


def binance_futures(path: str = "data/binance_futures.jsonl") -> list[dict]:
    """Banked funding-rate / open-interest readings, oldest first."""
    return _read_jsonl(path)


def angelone_fno(path: str = "data/angelone_fno.jsonl") -> list[dict]:
    """Banked Indian F&O readings, oldest first."""
    return _read_jsonl(path)


def funding_history(symbol: str, path: str = "data/binance_futures.jsonl"
                    ) -> list[tuple[str, float]]:
    """(timestamp, funding_rate) for one symbol, for testing the funding edge."""
    return [(r["ts"], r["funding_rate"]) for r in binance_futures(path)
            if r.get("symbol") == symbol and "funding_rate" in r]


def has_enough(path: str, minimum: int = 200) -> bool:
    """Whether enough readings are banked to test an edge (default 200)."""
    return len(_read_jsonl(path)) >= minimum
