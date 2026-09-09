"""The sixth model: a paper portfolio, scored like every other model.

What this is
------------
Hit rate does not pay. A model can be right 60% of the time and still lose
money if its winners are small and its losers are large, and a model can be
right 48% of the time and make money if the reverse holds. Nothing in the
first five models answers that question, because they score DIRECTION and
this asks about MONEY.

So this module replays every resolved prediction as if it had been taken as a
position, charges realistic costs on entry and exit, and keeps a running
equity curve. The output is one sentence the other five cannot produce:
after costs, following these signals would have turned the starting cash
into this much.

What this is NOT
----------------
It is not connected to a broker. There is no API key, no order endpoint, no
network call, and no code path that could place a real trade — not a flag
that must stay switched on, not a guard that could be edited: there is simply
no broker in the codebase. A paper trader that CAN reach a live account is
one config mistake away from being a live trader, and this system's whole
premise is that it must not be able to lie about, or act beyond, what it has
proven.

It is also not advice. It replays signals from models that have NOT cleared
their skill gate, which is the point: the replay is how we find out whether
they are worth money, in the same way the ledger is how we find out whether
they are right. Both answers are allowed to be no.

Determinism
-----------
Everything is computed from prices already stored in the ledger. Given the
same ledger, this produces the same equity curve every time, on any machine,
with no network. That is what makes it auditable rather than a story.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# One-way costs charged on entry AND on exit. 0.075% each side is a realistic
# retail round trip of 0.15% for liquid names once spread and fees are counted.
# It is deliberately not optimistic: a simulation that undercharges costs
# reports a profit the real world would never have paid out.
COST_PCT_PER_SIDE = 0.00075

# Fraction of current equity committed to one position. Small on purpose:
# the question is whether the signals have an edge, not how much leverage can
# amplify one. Sizing that risks the account cannot answer a question.
POSITION_PCT = 0.02

# How many positions may be open at once. Beyond this the portfolio is really
# just tracking the index, and a signal's contribution becomes unreadable.
MAX_CONCURRENT = 20

STARTING_CASH = 100_000.0


@dataclass
class Trade:
    """One completed round trip, entered and exited at ledger prices."""

    prediction_id: int
    model: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float                  # cash committed at entry
    gross_ret: float             # signed return before costs
    cost: float                  # cash paid in costs, both sides
    pnl: float                   # cash after costs
    opened_at: str

    def as_row(self) -> dict:
        return {
            "prediction_id": self.prediction_id, "model": self.model,
            "symbol": self.symbol, "side": self.side,
            "entry_price": self.entry_price, "exit_price": self.exit_price,
            "size": self.size, "gross_ret": self.gross_ret,
            "cost": self.cost, "pnl": self.pnl, "opened_at": self.opened_at,
        }


@dataclass
class Portfolio:
    """The result of replaying the ledger. Cash is notional and never real."""

    starting_cash: float = STARTING_CASH
    equity: float = STARTING_CASH
    trades: list[Trade] = field(default_factory=list)
    peak: float = STARTING_CASH
    max_drawdown: float = 0.0
    skipped_no_price: int = 0

    @property
    def total_pnl(self) -> float:
        return self.equity - self.starting_cash

    @property
    def total_return(self) -> float:
        return self.equity / self.starting_cash - 1.0

    @property
    def total_costs(self) -> float:
        return sum(t.cost for t in self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def win_rate(self) -> float | None:
        return (self.wins / len(self.trades)) if self.trades else None

    def by_model(self) -> dict[str, dict]:
        """Per-model money, because a portfolio total hides which model paid."""
        out: dict[str, dict] = {}
        for t in self.trades:
            row = out.setdefault(t.model, {"trades": 0, "pnl": 0.0,
                                           "wins": 0, "costs": 0.0})
            row["trades"] += 1
            row["pnl"] += t.pnl
            row["costs"] += t.cost
            row["wins"] += 1 if t.pnl > 0 else 0
        for row in out.values():
            row["win_rate"] = row["wins"] / row["trades"] if row["trades"] else None
        return out


def _resolved_rows(db_path: str, limit: int | None = None) -> list[dict]:
    """Every resolved prediction with both prices, oldest first.

    Oldest first matters: the equity curve compounds, so replaying out of
    order would produce a different and meaningless answer.
    """
    q = ("SELECT id,model,symbol,side,entry_price,exit_price,created_at "
         "FROM predictions "
         "WHERE hit IS NOT NULL AND entry_price IS NOT NULL "
         "AND exit_price IS NOT NULL "
         "ORDER BY created_at ASC, id ASC")
    if limit:
        q += f" LIMIT {int(limit)}"
    cols = ("id", "model", "symbol", "side", "entry_price", "exit_price",
            "created_at")
    with closing(sqlite3.connect(db_path)) as con:
        return [dict(zip(cols, r)) for r in con.execute(q)]


def replay(db_path: str, starting_cash: float = STARTING_CASH,
           position_pct: float = POSITION_PCT,
           cost_pct_per_side: float = COST_PCT_PER_SIDE,
           models: set[str] | None = None) -> Portfolio:
    """Replay the ledger as a portfolio and report what it would have paid.

    One prediction becomes one position: entered at the price the model saw,
    exited at the price the resolver found, charged costs both ways. A SELL
    signal earns the inverse of the move, as a short would.
    """
    book = Portfolio(starting_cash=starting_cash, equity=starting_cash,
                     peak=starting_cash)

    for row in _resolved_rows(db_path):
        if models and row["model"] not in models:
            continue
        entry, exit_ = row["entry_price"], row["exit_price"]
        if not entry or entry <= 0 or not exit_ or exit_ <= 0:
            # A prediction without both prices cannot be traded, and guessing
            # one would invent a P&L. Counted, not silently dropped.
            book.skipped_no_price += 1
            continue

        move = exit_ / entry - 1.0
        gross = move if row["side"].upper() == "BUY" else -move

        size = book.equity * position_pct
        cost = size * cost_pct_per_side * 2      # entry and exit
        pnl = size * gross - cost

        book.equity += pnl
        book.peak = max(book.peak, book.equity)
        drawdown = (book.peak - book.equity) / book.peak if book.peak else 0.0
        book.max_drawdown = max(book.max_drawdown, drawdown)

        book.trades.append(Trade(
            prediction_id=row["id"], model=row["model"], symbol=row["symbol"],
            side=row["side"], entry_price=entry, exit_price=exit_, size=size,
            gross_ret=gross, cost=cost, pnl=pnl, opened_at=row["created_at"]))

    return book


def verdict(book: Portfolio) -> str:
    """One sentence a person can act on, or decline to act on.

    Deliberately blunt about the difference between being right and making
    money, because that gap is the only thing this model exists to measure.
    """
    if not book.trades:
        return ("No resolved prediction carried both an entry and an exit "
                "price, so there is nothing to replay yet.")

    pct = book.total_return * 100
    n = len(book.trades)
    costs = book.total_costs
    if book.total_pnl > 0:
        head = (f"Following every signal would have returned {pct:+.2f}% "
                f"over {n:,} round trips, after paying {costs:,.0f} in costs.")
    else:
        head = (f"Following every signal would have LOST {abs(pct):.2f}% "
                f"over {n:,} round trips. Costs alone took {costs:,.0f}.")
    return (head + f" Worst peak-to-trough fall along the way: "
                   f"{book.max_drawdown * 100:.1f}%.")


def summary(book: Portfolio) -> str:
    """The console block, in the same plain register as the other models."""
    lines = [f"Paper portfolio — {len(book.trades):,} round trip(s) replayed",
             "", verdict(book), ""]

    if book.trades:
        lines.append(f"  Starting cash   {book.starting_cash:>12,.0f}")
        lines.append(f"  Ending equity   {book.equity:>12,.0f}")
        lines.append(f"  Costs paid      {book.total_costs:>12,.0f}")
        wr = book.win_rate
        lines.append(f"  Trades in profit{book.wins:>8,} of {len(book.trades):,}"
                     + (f" ({wr * 100:.0f}%)" if wr is not None else ""))
        lines.append("")
        lines.append("  By model:")
        for model, row in sorted(book.by_model().items(),
                                 key=lambda kv: -kv[1]["pnl"]):
            wr_m = row["win_rate"]
            lines.append(f"    {model:<14} {row['pnl']:>+11,.0f} "
                         f"over {row['trades']:>5,} trade(s)"
                         + (f", {wr_m * 100:.0f}% in profit" if wr_m else ""))

    if book.skipped_no_price:
        lines.append("")
        lines.append(f"  {book.skipped_no_price:,} resolved prediction(s) had "
                     "no usable price pair and were not replayed.")

    lines.append("")
    lines.append("This is a simulation on paper. No broker is connected and "
                 "no order was placed. It replays signals from models that "
                 "have not yet cleared their skill gate — finding out whether "
                 "they are worth money is exactly what it is for, and the "
                 "answer is allowed to be no.")
    return "\n".join(lines)


def write_state(book: Portfolio, path: str | Path = "paper.json") -> Path:
    """Persist the portfolio so the site can render it without recomputing."""
    out = Path(path)
    out.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "starting_cash": book.starting_cash,
        "equity": book.equity,
        "total_pnl": book.total_pnl,
        "total_return": book.total_return,
        "total_costs": book.total_costs,
        "trades": len(book.trades),
        "wins": book.wins,
        "win_rate": book.win_rate,
        "max_drawdown": book.max_drawdown,
        "skipped_no_price": book.skipped_no_price,
        "by_model": book.by_model(),
        "verdict": verdict(book),
        "recent_trades": [t.as_row() for t in book.trades[-25:]],
    }, indent=2), encoding="utf-8")
    return out
