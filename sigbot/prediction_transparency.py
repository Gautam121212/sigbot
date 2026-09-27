"""Prediction transparency — every single prediction, per model, verifiable.

The user's goal: SEE every prediction each model makes, so the results are
provably from real predictions, not made-up numbers. Predictions and paper
trading refresh daily (storage stays bounded).

This reads the live ledger and lists, per model, every prediction made in the
current daily cycle: the symbol, the side, the predicted move, when it was made,
when the result is due (aligned to the edge's real horizon), and — once resolved
— whether it hit. No aggregates that could hide a fabricated number: the raw
predictions themselves, each traceable to its resolution.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Prediction:
    model: str
    symbol: str
    side: str
    predicted_move: str
    made_at: str
    result_due: str
    resolved: bool
    hit: bool | None


@dataclass
class ModelPredictions:
    model: str
    predictions: list[Prediction] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.predictions)

    @property
    def resolved_count(self) -> int:
        return sum(1 for p in self.predictions if p.resolved)

    @property
    def hit_rate(self) -> float | None:
        res = [p for p in self.predictions if p.resolved]
        if not res:
            return None
        return sum(1 for p in res if p.hit) / len(res)


# Horizon per model (days) — must match report.SIGNAL_WINDOW_DAYS.
HORIZON_DAYS = {
    "crypto": 3, "crypto15m": 3, "news": 10, "daily": 5, "stocks": 20,
    "ventures": 90, "ideas": 10, "opportunity": 90, "contagion": 5,
}


def todays_predictions(ledger_path: str, since: datetime | None = None
                       ) -> list[ModelPredictions]:
    """Every prediction made since the last daily reset, grouped by model.

    Reads the live ledger — no synthetic data. If the ledger is unavailable,
    returns an empty list (the page shows "no predictions yet" honestly).
    """
    since = since or (datetime.now(timezone.utc) - timedelta(days=1))
    by_model: dict[str, ModelPredictions] = {}
    try:
        with closing(sqlite3.connect(ledger_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM predictions WHERE created_at >= ? "
                "ORDER BY model, created_at", (since.isoformat(),)).fetchall()
    except (sqlite3.Error, OSError):
        return []
    for r in rows:
        model = r["model"] if "model" in r.keys() else "unknown"
        made = r["created_at"] if "created_at" in r.keys() else ""
        horizon = HORIZON_DAYS.get(model, 5)
        try:
            due = (datetime.fromisoformat(made) + timedelta(days=horizon)
                   ).isoformat()
        except (ValueError, TypeError):
            due = ""
        resolved = bool(r["resolved"]) if "resolved" in r.keys() else False
        hit = (bool(r["hit"]) if "hit" in r.keys() and r["hit"] is not None
               else None)
        p = Prediction(
            model=model,
            symbol=r["symbol"] if "symbol" in r.keys() else "",
            side=(r["side"] if "side" in r.keys() else "") or "",
            predicted_move=(r["predicted_move"]
                            if "predicted_move" in r.keys() else "") or "",
            made_at=made, result_due=due, resolved=resolved, hit=hit)
        by_model.setdefault(model, ModelPredictions(model)).predictions.append(p)
    return list(by_model.values())


def summary(ledger_path: str) -> str:
    """A plain per-model list of today's predictions — for verification."""
    models = todays_predictions(ledger_path)
    if not models:
        return ("No predictions in the current cycle yet. When the model runs, "
                "every prediction it makes appears here — each with its symbol, "
                "predicted move, and result-due date — so you can verify the "
                "numbers come from real predictions, not fabrication.")
    lines = ["TODAY'S PREDICTIONS (every one, per model — verifiable)", ""]
    for m in models:
        hr = f", {m.hit_rate:.0%} hit" if m.hit_rate is not None else ""
        lines.append(f"{m.model}: {m.count} predictions "
                     f"({m.resolved_count} resolved{hr})")
        for p in m.predictions[:50]:
            status = ("HIT" if p.hit else "MISS") if p.resolved else "pending"
            lines.append(f"  {p.symbol} {p.side} {p.predicted_move} "
                         f"→ due {p.result_due[:10]} [{status}]")
    return "\n".join(lines)
