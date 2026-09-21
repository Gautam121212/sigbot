"""The monthly review: is sigbot still behaving the way the playbook says?

WHAT "LEARNING" MEANS HERE, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------------------
It does not mean the system rewrites its own rules. Changing rules
automatically on small samples is how a backtest becomes a fantasy: every
false finding this project caught — the gap-down signal that was one crash,
the capitulation cell that was 22 cases, the volatility cap that looked best
on a non-monotonic curve — is exactly what a self-tuning system would have
adopted.

So this does what a professional's monthly review does:

  * measures live behaviour against each playbook principle,
  * tracks each setup's live record against what its history promised,
  * flags drift, decay and candidates for promotion,
  * keeps a dated history so the trend is visible, not just the snapshot.

It recommends. A person decides. That is the playbook's own rule — records
are reviewed against the plan — applied to the system itself.

Verdicts are PASS, DRIFT (behaving unlike the playbook), or TOO EARLY (not
enough live trades to say). TOO EARLY is the honest answer for the first
months and must never be read as PASS.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PASS = "PASS"
DRIFT = "DRIFT"
EARLY = "TOO EARLY"

# Fewer live trades than this and a check reports TOO EARLY rather than a
# verdict. Thirty is small, but it is the point below which a single bad week
# can swing any average; below it, silence is more honest than a number.
MIN_TRADES = 30

# A setup is flagged for review once it has this many live trades.
REVIEW_AFTER = 120

HISTORY_FILE = "alignment_history.json"


@dataclass(frozen=True)
class Check:
    principle: str
    expectation: str
    measured: str
    verdict: str
    note: str = ""


def _stocks_trades(db_path: str) -> list[dict]:
    """Closed stocks trades with their recorded setup and stop distance."""
    with closing(sqlite3.connect(db_path)) as con:
        rows = con.execute(
            "SELECT entry_price, exit_price, expected_move, payload, hit, side "
            "FROM predictions WHERE model = 'stocks' AND hit IS NOT NULL "
            "AND entry_price > 0 AND exit_price > 0 "
            "ORDER BY resolve_after ASC, id ASC").fetchall()
    out = []
    for entry, exit_, stop, payload, hit, side in rows:
        try:
            info = json.loads(payload) if payload else {}
        except (TypeError, ValueError):
            info = {}
        move = exit_ / entry - 1.0
        if str(side).upper() == "SELL":
            move = -move
        r = move / stop if stop and stop > 0 else None
        out.append({"r": r, "hit": bool(hit), "setup": info.get("setup"),
                    "taken": info.get("taken", True)})
    return out


def check_losses_are_cut(trades: Sequence[dict]) -> Check:
    """Losers should close near one R. Much worse means stops are not holding."""
    losses = [t["r"] for t in trades if t["r"] is not None and t["r"] < 0]
    expect = "Losing trades close near -1 R: the stop, not a hope"
    if len(losses) < MIN_TRADES:
        return Check("Cut losers fast", expect, f"{len(losses)} losing trades",
                     EARLY)
    avg = sum(losses) / len(losses)
    verdict = PASS if avg >= -1.3 else DRIFT
    note = ("" if verdict == PASS else
            "Losses run past the stop. Either stops are gapping through or "
            "exits are not being honoured — the failure B84 was.")
    return Check("Cut losers fast", expect, f"average loss {avg:+.2f} R",
                 verdict, note)


def check_winners_run(trades: Sequence[dict]) -> Check:
    """Average win should be at least as large as average loss."""
    rs = [t["r"] for t in trades if t["r"] is not None]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    expect = "Average win at least as large as average loss"
    if len(wins) < MIN_TRADES // 2 or len(losses) < MIN_TRADES // 2:
        return Check("Let winners run", expect,
                     f"{len(wins)} wins, {len(losses)} losses", EARLY)
    ratio = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
    verdict = PASS if ratio >= 1.0 else DRIFT
    note = ("" if verdict == PASS else
            "Wins are smaller than losses. A high hit rate can hide this, and "
            "it is the pattern that made the washout setup lose to holding.")
    return Check("Let winners run", expect, f"payoff {ratio:.2f}", verdict, note)


def check_selectivity(considered: int, recorded: int) -> Check:
    """A professional looks at many and acts on few."""
    expect = "Records a small share of what it looks at"
    # A week of runs, not one. Capitulation fires on many names at once on a
    # panic day, so a single run's share swings with the regime; 597 looks —
    # one run — produced a false DRIFT.
    if considered < 5000:
        return Check("Be selective", expect, f"{considered} looked at", EARLY)
    share = recorded / considered
    verdict = PASS if share <= 0.10 else DRIFT
    note = ("" if verdict == PASS else
            "Recording most of what it sees is describing the market, not "
            "choosing within it — the failure the daily model had.")
    return Check("Be selective", expect, f"{share:.1%} of {considered:,} recorded",
                 verdict, note)


def check_streak_discipline(trades: Sequence[dict], pause_after: int) -> Check:
    """No trade should be TAKEN while a losing streak is at or past the pause."""
    expect = f"No new positions taken after {pause_after} straight losses"
    streak, breaches, seen = 0, 0, 0
    for t in trades:
        if streak >= pause_after and t.get("taken"):
            breaches += 1
        seen += 1
        streak = 0 if t["hit"] else streak + 1
    if seen < MIN_TRADES:
        return Check("Stand aside on a losing streak", expect,
                     f"{seen} closed trades", EARLY)
    verdict = PASS if breaches == 0 else DRIFT
    note = ("" if verdict == PASS else
            f"{breaches} position(s) taken during a streak. The pause is the "
            "rule that protected +0.241 R against -0.559 R historically.")
    return Check("Stand aside on a losing streak", expect,
                 f"{breaches} taken during a streak", verdict, note)


def check_both_schools(trades: Sequence[dict]) -> Check:
    """Momentum and washout failed in opposite years; both should be active."""
    from .scan import CANDIDATES

    styles = {c.name: c.style for c in CANDIDATES}
    seen = {styles.get(t["setup"]) for t in trades if t.get("setup")}
    expect = "Both momentum and dip-buying setups are firing"
    if len(trades) < MIN_TRADES:
        return Check("Run both schools", expect, f"{len(trades)} trades", EARLY)
    both = {"momentum", "reversion"} <= seen
    return Check("Run both schools", expect,
                 ", ".join(sorted(s for s in seen if s)) or "none",
                 PASS if both else DRIFT,
                 "" if both else
                 "Only one school is firing. They failed in opposite years "
                 "(2020 and 2022), so running one leaves the desk exposed to "
                 "the regime it cannot handle.")


@dataclass(frozen=True)
class SetupReview:
    setup: str
    trades: int
    live_r: float | None
    recommendation: str


def review_setups(trades: Sequence[dict]) -> list[SetupReview]:
    """Each setup's live record against its promise, with a recommendation.

    Recommendations only. Promoting on a lucky run and demoting on an unlucky
    one are equally wrong, which is why nothing here is applied automatically.
    """
    from .scan import CANDIDATES, PROVEN, tier_of

    by_setup: dict[str, list[float]] = {}
    for t in trades:
        if t.get("setup") and t["r"] is not None:
            by_setup.setdefault(t["setup"], []).append(t["r"])

    out = []
    for c in CANDIDATES:
        rs = by_setup.get(c.name, [])
        n = len(rs)
        live = (sum(rs) / n) if n else None
        if n < MIN_TRADES:
            rec = f"Keep watching — {n} live trade(s), needs {MIN_TRADES}."
        elif live is not None and live < 0:
            rec = ("DECAY — negative live R. Review whether its conditions "
                   "have changed; consider demoting or retiring it.")
        elif n >= REVIEW_AFTER and tier_of(c) != PROVEN and live and live > 0:
            rec = ("REVIEW FOR PROMOTION — positive live R on a full sample. "
                   "Re-run the money test against holding before promoting.")
        else:
            rec = "On track."
        out.append(SetupReview(c.name, n, round(live, 3) if live is not None
                               else None, rec))
    return out


def monthly_returns(db_path: str) -> list[tuple[str, float]]:
    """(YYYY-MM, return) for each month of the stocks paper book, oldest first.

    Each month's return is its P&L over the equity it started with, so a
    month after a drawdown is not flattered by a smaller base.
    """
    from .paper import replay

    book = replay(db_path, models={"stocks"})
    if not book.trades:
        return []
    by_month: dict[str, float] = {}
    for t in book.trades:
        key = str(t.opened_at)[:7]
        by_month[key] = by_month.get(key, 0.0) + t.pnl
    out, equity = [], float(book.starting_cash)
    for key in sorted(by_month):
        out.append((key, by_month[key] / equity if equity else 0.0))
        equity += by_month[key]
    return out


def check_growth(months: Sequence[tuple[str, float]]) -> Check:
    """Live monthly growth against the benchmark measured on history."""
    from .benchmarks import EXPECTED, HOLD_INDEX, judge_month, judge_run

    expect = (f"About {EXPECTED.net_avg * 100:+.2f}% a month net of costs, "
              f"against {HOLD_INDEX.avg_month * 100:+.2f}% for holding the index")
    if not months:
        return Check("Grow in line with history", expect, "no months yet", EARLY)
    last_key, last = months[-1]
    month_verdict, month_note = judge_month(last)
    run_verdict, run_note = judge_run([r for _k, r in months])
    verdict = (DRIFT if run_verdict == "BEHIND THE INDEX"
               else EARLY if run_verdict == "TOO EARLY" else PASS)
    return Check("Grow in line with history", expect,
                 f"{last_key}: {month_verdict}; over {len(months)} month(s): {run_verdict}",
                 verdict, f"{month_note} {run_note}")


def run_review(db_path: str, considered: int, recorded: int,
               pause_after: int) -> tuple[list[Check], list[SetupReview]]:
    trades = _stocks_trades(db_path)
    checks = [
        check_losses_are_cut(trades),
        check_winners_run(trades),
        check_selectivity(considered, recorded),
        check_streak_discipline(trades, pause_after),
        check_both_schools(trades),
        check_growth(monthly_returns(db_path)),
    ]
    return checks, review_setups(trades)


def record_history(checks: Sequence[Check], setups: Sequence[SetupReview],
                   path: str = HISTORY_FILE) -> None:
    """Append this review to the dated history, so trends are visible."""
    file = Path(path)
    history = []
    if file.exists():
        try:
            history = json.loads(file.read_text(encoding="utf-8"))
        except (TypeError, ValueError):
            history = []
    history.append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks": [asdict(c) for c in checks],
        "setups": [asdict(s) for s in setups],
    })
    file.write_text(json.dumps(history[-52:], indent=1), encoding="utf-8")


def describe(checks: Sequence[Check], setups: Sequence[SetupReview]) -> str:
    lines = ["Monthly review — live behaviour against the playbook", ""]
    for c in checks:
        lines.append(f"  [{c.verdict:<9}] {c.principle}")
        lines.append(f"      expected: {c.expectation}")
        lines.append(f"      measured: {c.measured}")
        if c.note:
            lines.append(f"      {c.note}")
    lines.append("")
    lines.append("  Setups, live against their promise:")
    for s in setups:
        live = "n/a" if s.live_r is None else f"{s.live_r:+.3f} R"
        lines.append(f"    {s.setup:<24} {s.trades:>4} trades  {live:>10}  {s.recommendation}")
    drifts = sum(c.verdict == DRIFT for c in checks)
    early = sum(c.verdict == EARLY for c in checks)
    lines.append("")
    if drifts:
        lines.append(f"  {drifts} principle(s) drifting. Each note says what "
                     "that pattern looked like when it caused a bug before.")
    elif early == len(checks):
        lines.append("  Everything is TOO EARLY. That is the correct answer "
                     "until there are live trades — not a pass.")
    lines.append("  Recommendations only. Nothing here changes a rule by "
                 "itself; promoting on luck and demoting on bad luck are "
                 "equally wrong.")
    return "\n".join(lines)
