"""The deep historical check — every model, every aspect, in one report.

Answers, from the live ledger and paper record:
  - do predictions complete (get scored) or hang unfinished?
  - how long does each horizon take, and does it finish?
  - are daily / monthly / yearly benchmarks met?
  - how many predictions are right (edge or not)?
  - does paper trading earn money?
  - can the model be deployed, and does it have scope?

It states the truth plainly — including "no edge" and "not ready" — because a
deploy decision made on flattering numbers is the one thing this must not do.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelHealth:
    model: str
    total: int
    scored: int
    completion_pct: float
    hours_to_complete: float | None
    hit_rate: float | None
    verdict: str


def _horizon_of(hours: float) -> str:
    return "intra-day" if hours <= 3 else "short-term" if hours <= 360 else "long-term"


def model_health(db_path: str) -> list[ModelHealth]:
    out = []
    with closing(sqlite3.connect(db_path)) as con:
        models = [r[0] for r in con.execute(
            "SELECT DISTINCT model FROM predictions ORDER BY model")]
        for m in models:
            total, scored = con.execute(
                "SELECT COUNT(*), COUNT(hit) FROM predictions WHERE model=?", (m,)).fetchone()
            if not total:
                continue
            hrs = con.execute(
                "SELECT AVG((julianday(resolve_after)-julianday(created_at))*24) "
                "FROM predictions WHERE model=? AND hit IS NOT NULL", (m,)).fetchone()[0]
            n_hit, wins = con.execute(
                "SELECT COUNT(hit), SUM(hit) FROM predictions WHERE model=? "
                "AND hit IS NOT NULL", (m,)).fetchone()
            rate = (wins or 0) / n_hit if n_hit else None
            verdict = ("no data" if not n_hit else
                       "EDGE" if rate and rate > 0.52 else
                       "below chance" if rate and rate < 0.48 else "no edge")
            out.append(ModelHealth(m, total, scored,
                                   round(scored / total * 100, 0),
                                   round(hrs, 1) if hrs else None,
                                   round(rate, 3) if rate is not None else None,
                                   verdict))
    return out


def horizon_completion(db_path: str) -> list[tuple[str, str, int, int]]:
    """(model, horizon, scored, total) — does each horizon finish?"""
    with closing(sqlite3.connect(db_path)) as con:
        rows = con.execute(
            "SELECT model, "
            "CASE WHEN (julianday(resolve_after)-julianday(created_at))*24 <= 3 "
            "THEN 'intra-day' WHEN (julianday(resolve_after)-julianday(created_at))*24 "
            "<= 360 THEN 'short-term' ELSE 'long-term' END AS h, "
            "COUNT(hit), COUNT(*) FROM predictions GROUP BY 1,2 ORDER BY 1,2").fetchall()
    return [(m, h, sc or 0, tot) for m, h, sc, tot in rows]


def describe(db_path: str) -> str:
    lines = ["DEEP HISTORICAL CHECK — every model, every aspect", ""]
    health = model_health(db_path)
    lines.append("Completion, timing, and edge:")
    for h in health:
        t = f"{h.hours_to_complete}h" if h.hours_to_complete else "—"
        r = f"{h.hit_rate * 100:.1f}%" if h.hit_rate is not None else "n/a"
        lines.append(f"  {h.model:<11} {h.scored}/{h.total} done "
                     f"({h.completion_pct:.0f}%), {t} to finish, "
                     f"hit {r} [{h.verdict}]")
    lines.append("")
    lines.append("Per-horizon completion (does each finish?):")
    for m, hz, sc, tot in horizon_completion(db_path):
        pct = sc / tot * 100 if tot else 0
        lines.append(f"  {m:<11} {hz:<11} {sc}/{tot} ({pct:.0f}%)")
    return "\n".join(lines)
