#!/usr/bin/env python3
"""What the daily schedule runs.

One script rather than four cron lines so the order is fixed and a failure in
one stage does not leave the rest half-done: resolve what has come due, make
today's predictions, rebuild the page.

Mondays additionally rotate the board and send a summary. The summary exists
because silence is ambiguous: no message could mean nothing cleared the gates,
which is the expected outcome most days, or it could mean the job has been
failing for a fortnight. One message a week removes the ambiguity.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_env() -> None:
    """Read .env if present.

    launchd does not inherit the environment of the Terminal window you set the
    variables in, so a scheduled run would otherwise have no credentials and
    fail to deliver — silently, since delivery errors are caught.
    """
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_env()

from sigbot import doctor  # noqa: E402
from sigbot.config import SETTINGS  # noqa: E402
from sigbot.runner import (  # noqa: E402
    default_messenger, run_cycle, run_daily, run_publish, run_resolve,
)
from sigbot.shadow import ShadowLedger  # noqa: E402
from sigbot.tiers import classify_tier  # noqa: E402
from sigbot.watchlist import Flag, Watchlist  # noqa: E402

STAGES = [
    ("resolve", run_resolve, "score predictions whose 24 hours are up"),
    ("daily", run_daily, "make today's predictions"),
    ("publish", run_publish, "rebuild the page"),
]


def weekly_summary(settings=SETTINGS) -> str:
    """A proof-of-life message. Sent whether or not anything fired."""
    lines = [f"Weekly summary — {datetime.now(timezone.utc):%Y-%m-%d}"]

    try:
        ledger = ShadowLedger(settings.shadow_db)
        resolved = hits = 0
        per_model = []
        for model in ("news", "daily", "contagion", "opportunity"):
            n, rate, lower = ledger.overall(model)
            if n:
                resolved += n
                hits += rate * n
                tier, _ = classify_tier(n, rate * n)
                per_model.append(f"  {model}: {n:,} checked, {rate:.0%} right, "
                                 f"worst case {lower:.0%} ({tier.value})")
        last = ledger.last_run("daily")
        if last:
            lines.append(f"Last run {last['ran_at'][:16].replace('T', ' ')} UTC — "
                         f"{last.get('note', '')}.")
        if resolved:
            lines.append(f"{resolved:,} predictions checked so far, "
                         f"{hits / resolved:.0%} right overall.")
            lines += per_model
        else:
            lines.append("Nothing has been checked yet. Predictions resolve a day "
                         "after they are made, so this fills in from tomorrow.")
    except Exception as exc:  # noqa: BLE001  # handled: stage recorded in `failed` and traceback printed
        lines.append(f"Could not read the ledger: {type(exc).__name__}: {exc}")

    try:
        wl = Watchlist(settings.watchlist_db)
        records: dict[str, tuple[int, float]] = {}
        led = ShadowLedger(settings.shadow_db)
        for model in ("news", "daily", "contagion", "opportunity"):
            for sym, (n, rate, _lo) in led.stats(model).items():
                pn, ph = records.get(sym, (0, 0.0))
                records[sym] = (pn + n, ph + rate * n)
        slots = wl.review(records)
        counts = {f: sum(1 for s in slots if s.flag is f) for f in Flag}
        lines.append(f"Board: {counts[Flag.GREEN]} ready, {counts[Flag.AMBER]} risky, "
                     f"{counts[Flag.RED]} avoid, {len(slots)} total.")
        if counts[Flag.GREEN] == 0:
            lines.append("Nothing is green yet. Early on that is correct — a board "
                         "that went green before the checks arrived would be guessing.")
        dropped = wl.graveyard(3)
        if dropped:
            lines.append("Recently dropped: "
                         + ", ".join(g["symbol"] for g in dropped))
    except Exception as exc:  # noqa: BLE001  # handled: prints the failure before continuing
        lines.append(f"Could not read the board: {type(exc).__name__}: {exc}")

    problems = [c for c in doctor.run(include_network=False)
                if c.status == doctor.FAIL]
    if problems:
        lines.append("Problems: " + "; ".join(f"{c.name} — {c.fix or c.detail}"
                                              for c in problems))
    else:
        lines.append("Health check clean.")
    return "\n".join(lines)


def main() -> int:
    started = datetime.now(timezone.utc)
    print(f"\n{'=' * 62}\nrun starting {started:%Y-%m-%d %H:%M} UTC")

    failed = []
    for name, fn, what in STAGES:
        print(f"\n--- {name}: {what}")
        try:
            fn()
        except Exception:  # noqa: BLE001 - one bad stage must not skip the rest
            failed.append(name)
            traceback.print_exc()

    if started.weekday() == 0 or "--summary" in sys.argv:
        print("\n--- cycle: weekly re-screen and rotation")
        try:
            run_cycle()
        except Exception:  # noqa: BLE001
            failed.append("cycle")
            traceback.print_exc()

        print("\n--- weekly summary")
        try:
            text = weekly_summary()
            print(text)
            default_messenger().send(text)
        except Exception:  # noqa: BLE001
            failed.append("summary")
            traceback.print_exc()

    print("\n--- health")
    for c in doctor.run(include_network=False):
        if c.status != doctor.OK:
            print(c.render())

    took = (datetime.now(timezone.utc) - started).total_seconds()
    if failed:
        print(f"\nfinished in {took:.0f}s with failures in: {', '.join(failed)}")
        return 1
    print(f"\nfinished in {took:.0f}s, all stages ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
