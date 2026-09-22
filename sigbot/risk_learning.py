"""The risk loop — separate from the learning loop, across every model.

TWO LOOPS, DELIBERATELY APART
-----------------------------
* The LEARNING loop (alignment.py, calibration.py, promotion.py) asks: does
  this model have a measurable EDGE? It is strict, because it guards real
  capital at scale.
* The RISK loop (here) asks a different question: among the bets the learning
  loop flagged RISKY, which kinds actually PAID? Thin-evidence stock setups,
  long-odds ventures, low-breadth sectors — each is a category of risk, and
  the point is to learn which categories reward being taken and which destroy
  capital.

They are kept apart on purpose. If risky outcomes fed the edge measurement, a
few lucky long shots would inflate the "edge" and teach the system to chase
risk. So the risk loop informs only the LABEL and the SIZING of a bet, never
whether a model has an edge and never a core position.

WHAT IT LEARNS, AND THE RULE IT NEVER BREAKS
--------------------------------------------
For each risk category it tracks realised outcomes and reports whether taking
that risk, sized small, was net positive. But it enforces the barbell rule
above everything: a category can be "worth taking" ONLY if every bet in it had
a capped, survivable downside. A category that ever risked ruin is marked
NEVER, whatever its average — because one uncapped loss ends the game, and no
average survives that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RISK_LOG = "risk_loop.jsonl"
RISK_LOG_MAX = 5000
MIN_OUTCOMES = 30


def record_risky_bet(model: str, category: str, *, downside_capped: bool,
                     amount_risked_pct: float, outcome_multiple: float | None,
                     note: str = "", path: str = RISK_LOG) -> bool:
    """Log one risky bet from ANY model.

    outcome_multiple is the realised return as a multiple of the amount risked
    (None until known: -1 total loss, 0 break-even, +4 a 5x). amount_risked_pct
    is the share of capital at stake — the survivability check.
    """
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model, "category": category,
        "downside_capped": bool(downside_capped),
        "amount_risked_pct": round(float(amount_risked_pct), 4),
        "outcome_multiple": outcome_multiple, "note": note[:160],
    }
    try:
        p = Path(path)
        old = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        p.write_text("\n".join((old + [json.dumps(row)])[-RISK_LOG_MAX:]) + "\n",
                     encoding="utf-8")
        return True
    except OSError:
        return False


@dataclass(frozen=True)
class RiskVerdict:
    model: str
    category: str
    bets: int
    scored: int
    avg_outcome: float | None
    worst_risked_pct: float
    all_capped: bool
    verdict: str


def _verdict(scored: int, avg: float | None, all_capped: bool,
             worst_pct: float) -> str:
    # The barbell rule first: any uncapped downside, or any bet large enough to
    # hurt, disqualifies the category no matter how well it did.
    if not all_capped:
        return "NEVER — an uncapped bet risks ruin, whatever the average"
    if worst_pct > 0.05:
        return "NEVER — bets too large to survive a cluster of losses"
    if scored < MIN_OUTCOMES:
        return "TOO EARLY"
    if avg is None:
        return "TOO EARLY"
    if avg > 0.1:
        return "PAYS — this risk, sized small, has been worth taking"
    if avg < -0.1:
        return "COSTS — this risk has not paid; take fewer, smaller"
    return "NEUTRAL — no clear signal yet"


def verdicts(path: str = RISK_LOG) -> list[RiskVerdict]:
    p = Path(path)
    if not p.exists():
        return []
    groups: dict[tuple[str, str], list[dict]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        groups.setdefault((row.get("model", "?"), row.get("category", "?")), []).append(row)
    out = []
    for (model, category), rows in sorted(groups.items()):
        scored = [r["outcome_multiple"] for r in rows if r.get("outcome_multiple") is not None]
        avg = sum(scored) / len(scored) if scored else None
        all_capped = all(r.get("downside_capped") for r in rows)
        worst = max((r.get("amount_risked_pct", 0.0) for r in rows), default=0.0)
        out.append(RiskVerdict(model, category, len(rows), len(scored),
                               round(avg, 3) if avg is not None else None,
                               round(worst, 4), all_capped,
                               _verdict(len(scored), avg, all_capped, worst)))
    return out


def describe(path: str = RISK_LOG) -> str:
    vs = verdicts(path)
    if not vs:
        return ("Risk loop (separate from the learning loop): no risky bets "
                "logged yet. Risky bets from every model are recorded here with "
                "their downside and outcome, so the system learns which risks pay.")
    lines = ["Risk loop — which risks paid (separate from edge measurement)", ""]
    for v in vs:
        avg = "n/a" if v.avg_outcome is None else f"{v.avg_outcome:+.2f}x"
        lines.append(f"  [{v.verdict.split(' — ')[0]:<10}] {v.model}/{v.category:<20} "
                     f"{v.scored}/{v.bets} scored, avg {avg}, worst bet "
                     f"{v.worst_risked_pct:.1%} of capital")
        lines.append(f"       {v.verdict}")
    lines.append("")
    lines.append("  This shapes only the LABEL and SIZE of a bet — never whether "
                 "a model has an edge, never a core position.")
    return "\n".join(lines)
