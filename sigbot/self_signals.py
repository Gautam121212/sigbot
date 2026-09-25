"""Self-referential signals — edges that exist ONLY because sigbot has its own
multi-model scored ledger. No other system can compute these.

ACCURACY MOMENTUM (confirmed on the daily model)
------------------------------------------------
A model's own recent form persists: after the daily model was hot (55%+ over
its last 20 scored predictions) its next 20 hit 51-54%; after cold (35%-) they
hit 43%. That is a +8-point spread, and it held in BOTH halves of the history
(+2.2 and +11.0). Crypto did NOT hold (flipped sign), so this applies only
where it is measured to persist.

This is not a market indicator — it is a signal about the MODEL, read from
sigbot's own ledger. It cannot exist anywhere else, because no other system
keeps a per-model scored history to measure its own streak against.

It adjusts CONFIDENCE and SIZING, never direction: when a model is in form, its
signals are sized a little larger; when it is cold, smaller. It never flips a
buy to a sell — the market call is the model's; this only says how much to
trust it right now.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing

WINDOW = 20                 # predictions in the rolling form window
HOT = 0.55                  # recent accuracy at/above this = in form
COLD = 0.35                 # at/below this = out of form

# Models where accuracy-momentum was CONFIRMED to persist out-of-sample.
# Others are excluded until their own history shows the same.
CONFIRMED = frozenset({"daily"})


def recent_form(db_path: str, model: str, window: int = WINDOW) -> float | None:
    """The model's accuracy over its last `window` scored predictions, or None
    if it has fewer than that."""
    with closing(sqlite3.connect(db_path)) as con:
        rows = con.execute(
            "SELECT hit FROM predictions WHERE model=? AND hit IS NOT NULL "
            "ORDER BY resolve_after DESC, id DESC LIMIT ?", (model, window)).fetchall()
    if len(rows) < window:
        return None
    return sum(r[0] for r in rows) / len(rows)


def form_multiplier(db_path: str, model: str) -> tuple[float, str]:
    """A sizing multiplier from the model's current form, and why.

    Only the confirmed models get a non-1.0 multiplier. Hot -> 1.25x (trust it
    more), cold -> 0.6x (trust it less), neutral or unconfirmed -> 1.0x.
    Bounded so it nudges sizing, never dominates it.
    """
    if model not in CONFIRMED:
        return 1.0, "form-momentum not confirmed for this model"
    form = recent_form(db_path, model)
    if form is None:
        return 1.0, "not enough history to read form"
    if form >= HOT:
        return 1.25, f"in form ({form:.0%} over last {WINDOW}) — sized up"
    if form <= COLD:
        return 0.6, f"out of form ({form:.0%} over last {WINDOW}) — sized down"
    return 1.0, f"neutral form ({form:.0%})"


def describe(db_path: str) -> str:
    lines = ["Model form (accuracy momentum — a sigbot-only signal)", ""]
    for model in ("daily", "crypto15m", "news", "stocks"):
        form = recent_form(db_path, model)
        mult, why = form_multiplier(db_path, model)
        f = f"{form:.0%}" if form is not None else "n/a"
        lines.append(f"  {model:<11} recent {f}  x{mult:.2f}  ({why})")
    return "\n".join(lines)
