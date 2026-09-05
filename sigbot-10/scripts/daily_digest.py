#!/usr/bin/env python3
"""Daily digest — sends every day, whether or not anything is trade-ready.

The daily job only messaged when a forecast cleared the gates, which on a
normal day is never. That is right for *trade* alerts and wrong for everything
else: you cannot watch a system learn if it only speaks when it is certain.

This sends the working state instead — what it checked, what it got right and
wrong, what it is leaning on today and how much evidence sits behind each one.
Tiers still gate what may be called actionable; they no longer gate what you
are allowed to see.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TELEGRAM_LIMIT = 3900          # the real cap is 4096; leave room for the footer
TOP_N = 8


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _rows(db: Path, sql: str, args=()) -> list:
    if not db.exists():
        return []
    try:
        with sqlite3.connect(db) as con:
            return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def build() -> str:
    from sigbot.export_app import MISS_PLAIN
    from sigbot.stats import wilson_interval

    shadow, watch = ROOT / "shadow.db", ROOT / "watchlist.db"
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat()
    out = [f"Sigbot — {datetime.now(timezone.utc):%a %d %b}"]

    # --- what it did today
    made = _rows(shadow, "SELECT COUNT(*), COALESCE(SUM(alerted),0) FROM predictions "
                         "WHERE created_at >= ?", (day_ago,))
    if made and made[0][0]:
        total, alerted = made[0]
        out.append(f"\nRan on {total} assets. {alerted} cleared the gates; the rest "
                   "are recorded and will be checked tomorrow.")
    else:
        out.append("\nNo forecasts recorded today — the job may not have run.")

    # --- what came back
    # Resolution happens ~24h after creation, so the window is on resolve_after
    # between yesterday and now — not created_at, which would catch today's
    # unresolved batch and report "nothing came due" every single day.
    now = datetime.now(timezone.utc).isoformat()
    checked = _rows(shadow,
                    "SELECT COUNT(*), COALESCE(SUM(hit),0) FROM predictions "
                    "WHERE hit IS NOT NULL AND resolve_after >= ? AND resolve_after <= ?",
                    (day_ago, now))
    if checked and checked[0][0]:
        n, hits = checked[0]
        lo, _ = wilson_interval(hits, n, 0.90)
        out.append(f"\nCHECKED YESTERDAY\n{n} came due, {hits} were right "
                   f"({hits / n:.0%}). Worst case on that sample: {lo:.0%}.")
        misses = _rows(shadow,
                       "SELECT symbol, outcome_mode, ROUND(realised_ret*100,1) "
                       "FROM predictions WHERE hit=0 AND resolve_after >= ? "
                       "AND resolve_after <= ? "
                       "ORDER BY ABS(realised_ret) DESC LIMIT 4", (day_ago, now))
        for sym, mode, moved in misses:
            head = MISS_PLAIN.get(mode or "unexplained", ("Missed", ""))[0]
            out.append(f"  {sym}: {head.lower()}, moved {moved:+.1f}%")
    else:
        out.append("\nCHECKED YESTERDAY\nNothing came due yet. The first batch "
                   "resolves 24 hours after it was made.")

    # --- what it is leaning on now, gated or not
    leaning = _rows(shadow,
                    "SELECT symbol, side, score, ROUND(expected_move*100,2) "
                    "FROM predictions WHERE created_at >= ? AND score IS NOT NULL "
                    "ORDER BY score DESC LIMIT ?", (day_ago, TOP_N))
    if leaning:
        out.append("\nLEANING TOWARDS (not advice — evidence shown so you can judge)")
        for sym, side, score, move in leaning:
            n_rec = _rows(shadow, "SELECT COUNT(*) FROM predictions WHERE symbol=? "
                                  "AND hit IS NOT NULL", (sym,))
            seen = n_rec[0][0] if n_rec else 0
            note = "no record yet" if seen < 25 else f"{seen} checks behind it"
            out.append(f"  {sym} {side} {score:.0%}  {move:+.2f}%  ({note})")

    # --- the board
    board = _rows(watch, "SELECT COUNT(*) FROM watchlist")
    size = board[0][0] if board else 0
    if size:
        dropped = _rows(watch, "SELECT symbol FROM graveyard WHERE dropped_at >= ?",
                        (day_ago,))
        line = f"\nBOARD\n{size} assets."
        if dropped:
            line += " Replaced today: " + ", ".join(d[0] for d in dropped[:4]) + "."
        out.append(line)
    else:
        # An empty board is not zero coverage — the models fall back to the
        # default list. Reporting "0 assets" made a working system look dead.
        out.append("\nBOARD\nNot built yet, so this is running on the default "
                   "list rather than the screened 100. Run:\n"
                   "  python scripts/run_screen.py --provider yahoo --apply")

    out.append("\nEvery number here comes from predictions checked against what "
               "actually happened. Confidence rises only as the count does.")

    text = "\n".join(out)
    return text if len(text) <= TELEGRAM_LIMIT else text[:TELEGRAM_LIMIT] + "\n[trimmed]"


def main() -> int:
    load_env()
    text = build()
    print(text)
    try:
        from sigbot.setup_delivery import send

        send(text)
        print("\nsent")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\nnot sent: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
