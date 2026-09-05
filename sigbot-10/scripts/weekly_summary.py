#!/usr/bin/env python3
"""Weekly proof-of-life. Sends whether or not anything fired.

Silence from this system is the normal state — most weeks nothing clears the
gates. But silence from a working system and silence from a job that has been
crashing since Tuesday look identical on a phone. This closes that gap: one
message a week that always arrives, saying what was checked and what was found.

Reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from the environment, falling back to
a .env file beside this repo, because launchd does not inherit your shell.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def summarise() -> str:
    from sigbot.stats import wilson_interval

    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    shadow, watch = ROOT / "shadow.db", ROOT / "watchlist.db"
    lines = [f"Weekly summary — {datetime.now(timezone.utc):%d %b %Y}", ""]

    if not shadow.exists():
        return "\n".join(lines + ["Nothing has run yet."])

    with sqlite3.connect(shadow) as con:
        made = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE created_at >= ?", (since,)
        ).fetchone()[0]
        checked, hits = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(hit),0) FROM predictions "
            "WHERE hit IS NOT NULL AND resolve_after >= ?", (since,)
        ).fetchone()
        total, total_checked = con.execute(
            "SELECT COUNT(*), COUNT(hit) FROM predictions").fetchone()
        try:
            runs = con.execute(
                "SELECT COUNT(*) FROM runs WHERE ran_at >= ?", (since,)).fetchone()[0]
        except sqlite3.OperationalError:
            runs = 0
        modes = con.execute(
            "SELECT outcome_mode, COUNT(*) FROM predictions "
            "WHERE hit=0 AND outcome_mode IS NOT NULL AND resolve_after >= ? "
            "GROUP BY outcome_mode ORDER BY 2 DESC", (since,)).fetchall()

    lines.append(f"The job ran {runs} time(s) this week.")
    lines.append(f"Signals sent: {made}. Predictions checked: {checked}.")
    if checked:
        rate = hits / checked
        lo, _ = wilson_interval(hits, checked, 0.90)
        lines.append(f"Right {rate:.0%} of them, worst case {lo:.0%}.")
    lines.append(f"All time: {total} made, {total_checked} checked.")

    if modes:
        lines += ["", "Where it went wrong this week:"]
        lines += [f"  {m.replace('_', ' ')}: {c}" for m, c in modes[:4]]

    if watch.exists():
        try:
            with sqlite3.connect(watch) as con:
                board = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
                dropped = con.execute(
                    "SELECT COUNT(*) FROM graveyard WHERE dropped_at >= ?",
                    (since,)).fetchone()[0]
            lines += ["", f"Board: {board} assets, {dropped} replaced this week."]
        except sqlite3.OperationalError:
            pass

    if made == 0:
        lines += ["", "No signal cleared the gates. That is the usual week, and "
                      "it means nothing is being invented."]
    return "\n".join(lines)


def main() -> int:
    load_env()
    text = summarise()
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
