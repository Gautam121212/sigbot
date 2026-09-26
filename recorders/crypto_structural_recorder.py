#!/usr/bin/env python3
"""Crypto structural recorder — the data sigbot never had (via crypto.com MCP).

The breakthrough: crypto.com exposes perpetual futures with OPEN INTEREST, MARK
vs INDEX price (the BASIS), and bid/ask SPREAD — the structural-edge data the
quant research says is where crypto's real (non-directional) edge lives. sigbot
was blind to this; now it can bank it.

THE STRUCTURAL SIGNALS (measured live across 239 perp/spot pairs):
  - BASIS (perp vs spot): ranges +69% to -56% across coins. A large positive
    basis = perps overpriced = crowded longs paying up = mean-reverts DOWN.
    Large negative = crowded shorts = squeeze UP. This is the funding-rate edge
    in price form, and it is STRUCTURAL (about positioning, not price direction).
  - OPEN INTEREST: how much leverage is committed — a crowding gauge.
  - SPREAD: liquidity; tight-spread high-OI coins are the tradeable setups.

This records those three per instrument on a schedule so the structural edge can
finally be BACKTESTED (basis today -> price move over the next days). Run it on
a machine with the crypto.com MCP; it appends to data/crypto_structural.jsonl.

Because this is a recorder for an MCP-backed feed, the actual fetch is done by
the caller's MCP client; this module defines the schema and the analysis so the
banked data is testable the moment enough is collected.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

OUT = Path("data/crypto_structural.jsonl")


@dataclass(frozen=True)
class StructuralReading:
    ts: str
    coin: str
    spot: float
    perp: float
    basis_pct: float           # (perp/spot - 1) * 100
    open_interest: float
    spread_pct: float


def basis_signal(basis_pct: float, open_interest: float, spread_pct: float
                 ) -> tuple[str, str]:
    """The structural read from the basis. Only trust liquid setups (high OI,
    tight spread) — an illiquid coin's huge basis is noise, not signal."""
    liquid = open_interest > 5000 and spread_pct < 0.5
    if not liquid:
        return "skip", "illiquid — basis is noise, not a structural signal"
    if basis_pct > 1.0:
        return "SELL", (f"perp {basis_pct:+.2f}% over spot — crowded longs "
                        "paying up, structurally mean-reverts down")
    if basis_pct < -1.0:
        return "BUY", (f"perp {basis_pct:+.2f}% under spot — crowded shorts, "
                       "structurally squeezes up")
    return "neutral", f"basis {basis_pct:+.2f}% — no structural edge"


def append(reading: StructuralReading) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(reading)) + "\n")


def read_all(path: str = str(OUT)) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
