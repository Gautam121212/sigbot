"""Export real system state to JSON for the app.

The app displays this file and nothing else. That constraint is deliberate: it
makes it structurally impossible for the interface to show a number the backend
did not produce.

Every field the UI renders comes from the ledger, the pattern registry or the
rubrics. There is no `portfolio_value` and no `accuracy` key, because neither
exists in the system. Where there is no evidence yet, the export says so and the
app shows that instead of a placeholder.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import DESCRIPTIONS, POOL
from .patterns import PatternRegistry, Stage
from .shadow import ShadowLedger
from .skips import record_skip
from .tiers import Tier, classify_tier, observations_needed
from .watchlist import Flag, Watchlist

# Every key in MODEL_META needs one, or adding a model raises a KeyError deep
# in the export rather than at the definition. A test now checks the two maps
# agree, because the failure surfaced twenty-four tests away from its cause.
ACCENTS = {"news": "teal", "daily": "purple", "contagion": "red",
           "crypto15m": "amber", "opportunity": "green"}

# Plain-English names for what went wrong. The stored codes are precise; these
# are what a person reads at 8am without a finance degree.
MISS_PLAIN = {
    "direction_wrong": ("Went the other way",
                        "We said up, it went down. No part of the move went our way."),
    "reversal": ("Started right, then turned",
                 "It moved our way first, then swung back past the starting point."),
    "magnitude_short": ("Right, but too small",
                        "The direction was correct. The move was smaller than the "
                        "cost of trading it, so being right earned nothing."),
    "gap_against": ("Gapped overnight",
                    "It opened well against us before trading started. There was no "
                    "chance to react."),
    "unexplained": ("No clear reason",
                    "Nothing in the price action explains it. If this one keeps "
                    "coming up, the idea has no edge here."),
    "win": ("Worked", "It moved the way we expected, by enough to matter."),
}

from .horizons import horizon_for

MODEL_META = {
    "news": ("News scanner", "Scores stories for whether they move an asset"),
    "daily": ("Daily outlook", "Next-session direction on the watchlist"),
    "contagion": ("Follow-on moves", "Which names react after a large move elsewhere"),
    # Model E. Missing from this map meant it recorded thousands of forecasts,
    # filled Learned and Missed, and never appeared on the home page — the one
    # model producing most of the evidence was the one you could not see.
    "crypto15m": ("Crypto, every 3 hours",
                  "One-hour direction on the most traded pairs"),
    "opportunity": ("Opportunities", "Investments and business gaps, rated on evidence"),
}


@dataclass
class ModelView:
    id: str
    name: str
    subtitle: str
    accent: str
    tier: str
    tier_label: str
    resolved: int
    made: int
    last_run: str
    hit_rate: float | None
    lower_bound: float | None
    needed_for_trade: int | None
    status_line: str
    alerts: list[dict]
    # Defaults go last: a dataclass rejects a non-default field after a
    # defaulted one, which is what the first attempt at this hit.
    badge: str = ""
    window: str = ""
    badge_colour: str = ""
    falsifier: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _status_line(tier: Tier, n: int, rate: float | None, need: int | None) -> str:
    if n == 0:
        return "Nothing checked yet. It stays quiet until it has something to show."
    if tier is Tier.SILENT:
        base = f"Checked {n:,} times, right {rate:.0%} of the time. Not enough to act on."
        # "Never, however long it runs" is a claim about the true hit rate,
        # made from a measured one. At 48% of 300 checks drawn from a handful
        # of market days, the honest statement is that this rate would not
        # clear the bar if it held — not that it will hold. Overclaiming a null
        # is the same error as overclaiming an edge, pointed the other way.
        return base + (
            f" It would need about {need:,} checks at this rate." if need else
            " A rate this far below the bar would not clear it at any sample "
            "size — though whether it stays this low is what the coming weeks "
            "answer, not this number.")
    return f"Checked {n:,} times, right {rate:.0%} of the time."


def _board(ledger: ShadowLedger, watchlist_path: str) -> dict:
    """The rolling 100, coloured from each asset's own record."""
    try:
        wl = Watchlist(watchlist_path)
        if not wl.symbols():
            wl.seed(POOL)
        records: dict[str, tuple[int, float]] = {}
        for model in MODEL_META:
            for sym, (n, rate, _lo) in ledger.stats(model).items():
                pn, ph = records.get(sym, (0, 0.0))
                records[sym] = (pn + n, ph + rate * n)
        slots = wl.review(records, DESCRIPTIONS)
    except Exception as exc:  # noqa: BLE001
        # Say the board failed rather than rendering an empty one. An empty board
        # and a broken board look identical on screen and mean opposite things.
        record_skip("board", "watchlist", exc)
        return {"size": 0, "counts": {}, "assets": [], "graveyard": [],
                "note": f"The board could not be built: {type(exc).__name__}: {exc}. "
                        "This is a failure, not an empty board."}

    # Two gates. Admission asks whether an asset has been checked enough for a
    # colour to mean anything; the colour then says what those checks show.
    # Showing all hundred regardless produced a wall of amber tiles that said
    # the same thing for months — a display carrying no information.
    from .watchlist import admitted, waiting_note

    # Everything stays on the board. The split is which gate it has passed:
    # a TESTING asset is visible and grey, a coloured one has earned its
    # colour. Hiding the untested ones answered the complaint that the board
    # said nothing by showing less, which is the wrong direction.
    measured: list[dict] = []
    waiting: list[dict] = []
    for slot in slots:
        row = slot.to_dict()
        n = int(row.get("checks") or row.get("n") or 0)
        (measured if admitted(n) else waiting).append(row)
        if not admitted(n):
            row["waiting_note"] = waiting_note(n)

    flag_counts: dict[str, int] = {f.value: sum(1 for s in slots if s.flag is f)
                                   for f in Flag}
    return {
        "size": len(slots),
        "counts": flag_counts,
        # Coloured first, then the ones still being tested — one list, so the
        # board shows all hundred and the colour says which gate each passed.
        "assets": measured + waiting,
        "measured_count": len(measured),
        "waiting": waiting,
        "waiting_count": len(waiting),
        "graveyard": wl.graveyard(12),
        "note": ("Green means the record clears the bar. Amber means measurable "
                 "but weak. Red means even the most flattering reading loses to "
                 "a coin flip, and it is queued for replacement."
                 + (f" Grey means being tested: {len(waiting)} asset(s) are "
                    "forecast and scored every day but have too few resolved "
                    "checks for a colour to mean anything yet." if waiting
                    else "")),
    }


def build_opportunities(cards=None, candidates=None, limit: int = 20) -> list[dict]:
    """Plain-language opportunity cards for the app.

    Empty is the normal state. The scan speaks only when something new matched,
    so an empty list means nothing arrived, not that anything is broken.
    """
    from .plain_opportunities import from_candidate, from_thesis

    out: list[dict] = []
    for item, convert in [(c, from_thesis) for c in (cards or [])] + \
                         [(c, from_candidate) for c in (candidates or [])]:
        try:
            card = convert(item)
        except Exception as exc:  # noqa: BLE001
            record_skip("opportunity_card", str(getattr(item, "title", item))[:40], exc)
            continue
        out.append({"title": card.title, "kind": card.kind, "colour": card.colour,
                    "verdict": card.verdict, "summary": card.summary,
                    "answered": card.answered, "unanswered": card.unanswered,
                    "money": card.money, "sources": card.sources})
    # Green, amber, grey. The card dict holds mixed types, so the colour is
    # read out explicitly rather than indexed inside the key function.
    order = {"#00e676": 0, "#ffd93d": 1, "#8b8b9a": 2}
    out.sort(key=lambda c: order.get(str(c["colour"]), 3))
    return out[:limit]


def build_charts(bars_by_symbol: dict, kinds: dict[str, str],
                 descriptions: dict[str, str] | None = None, days: int = 180) -> list[dict]:
    """Render a chart block per asset. Skips any that fail rather than aborting."""
    from .chart_svg import chart_block

    descriptions = descriptions or DESCRIPTIONS
    out = []
    for sym, bars in bars_by_symbol.items():
        try:
            block = chart_block(bars, sym, descriptions.get(sym, ""), days)
        except Exception as exc:  # noqa: BLE001
            record_skip("charts", sym, exc)
            continue
        out.append({"symbol": sym, "kind": kinds.get(sym, "equity"),
                    "days": days, "block": block})
    return out


def build_export(db_path: str = "shadow.db", patterns_path: str = "patterns.db",
                 watchlist_path: str = "watchlist.db", max_alerts: int = 40,
                 charts: list[dict] | None = None, is_sample: bool = False,
                 opportunities: list[dict] | None = None) -> dict:
    ledger = ShadowLedger(db_path)
    models: list[ModelView] = []
    all_alerts: list[dict] = []

    def _activity(model_id: str) -> tuple[int, str]:
        """Forecasts recorded, and when the job last ran.

        "Checked 0" with nothing else is indistinguishable from a dead job —
        which is the complaint: three model pages read "nothing checked yet"
        while their jobs ran every few hours and simply found nothing that
        cleared a bar. Finding nothing is work; the page has to show the work.
        """
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(ledger.path)) as con:
            made = con.execute("SELECT COUNT(*) FROM predictions WHERE model=?",
                               (model_id,)).fetchone()[0]
        job = {"opportunity": "opportunity"}.get(model_id, model_id)
        run = ledger.last_run(job)
        if run is None:
            return made, ""
        when = str(run["ran_at"])[:16].replace("T", " ")
        return made, (f"Last ran {when} UTC, looked at "
                      f"{run['considered']:,} thing(s), "
                      f"{run['signals']:,} cleared its bar.")

    for model_id, (name, subtitle) in MODEL_META.items():
        activity_made, activity_line = _activity(model_id)
        n, rate, lower = ledger.overall(model_id)
        tier, _ = classify_tier(n, (rate * n) if n else 0.0)
        need = observations_needed(Tier.TRADE, rate) if n and rate else None

        alerts = [
            {"model": model_id, "symbol": sym, "tier": t.value,
             "description": DESCRIPTIONS.get(sym, ""),
             "detail": f"{cnt:,} checks, right {r:.0%} of the time, {lo:.0%} worst case",
             "resolved": cnt}
            for sym, (cnt, r, lo) in sorted(
                ledger.stats(model_id).items(), key=lambda kv: -kv[1][0])[:8]
            for t, _, _ in [ledger.tier(model_id, sym)]
        ]
        all_alerts.extend(alerts)

        models.append(ModelView(
            id=model_id, name=name, subtitle=subtitle, accent=ACCENTS[model_id],
            badge=horizon_for(model_id).badge,
            window=horizon_for(model_id).window,
            badge_colour=horizon_for(model_id).colour,
            falsifier=horizon_for(model_id).falsifier,
            made=activity_made, last_run=activity_line,
            tier=tier.value, tier_label=tier.label, resolved=n,
            hit_rate=round(rate, 4) if n else None,
            lower_bound=round(lower, 4) if n else None,
            needed_for_trade=need,
            status_line=_status_line(tier, n, rate if n else None, need),
            alerts=alerts,
        ))

    try:
        reg = PatternRegistry(patterns_path)
        patterns = {
            s.value.lower(): [
                {"key": r.pattern_key, "model": r.model, "symbol": r.symbol,
                 "n": r.quoted_n,
                 "rate": round(r.hit_rate, 4) if r.quoted_n else None,
                 "lower": round(r.lower_bound, 4) if r.quoted_n else None}
                for r in reg.by_stage(s)[:12]
            ] for s in Stage
        }
        reg.close()
    except Exception as exc:  # noqa: BLE001
        record_skip("patterns", "registry", exc)
        patterns = {s.value.lower(): [] for s in Stage}

    board = _board(ledger, watchlist_path)
    learning = _learning_feed(ledger)

    # The sixth model's state, if it has run. Absent is a normal state and
    # renders as "not run yet" rather than as zeros, which would read as a
    # flat return that never happened.
    paper_state = None
    try:
        import json as _json
        _pf = Path("paper.json")
        if _pf.exists():
            paper_state = _json.loads(_pf.read_text())
    except Exception:  # noqa: BLE001  # handled: absent or unreadable state renders as "not run yet"
        paper_state = None
    failures = _failure_feed(ledger)
    alertable = sum(1 for m in models if m.tier in ("CAUTION", "TRADE"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "headline": {
            "models_total": len(models),
            "models_alertable": alertable,
            "observations_total": sum(m.resolved for m in models),
            "confirmed_patterns": len(patterns.get("confirmed", [])),
            "message": (
                f"{alertable} of {len(models)} models have earned the right to alert."
                if alertable else
                "None of them has earned the right to alert yet. Early on that is "
                "exactly what should happen — it means nothing is being made up."
            ),
        },
        "models": [m.to_dict() for m in models],
        "board": board,
        "charts": charts or [],
        "opportunities": opportunities or [],
        "learning": learning,
        "paper": paper_state,
        "failures": failures,
        "alerts": all_alerts[:max_alerts],
        "patterns": patterns,
        "disclaimer": (
            "Every number here comes from predictions that were checked against what "
            "actually happened. None of it predicts profit, and none of it is "
            "financial advice."
        ),
    }


def _pretty_model(model_id: str) -> str:
    return MODEL_META.get(model_id, (model_id, ""))[0]


def _mean(xs: list[float]) -> float | None:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else None


def _group(rows: list[dict]) -> list[dict]:
    """Collapse repeats into one entry per asset and outcome.

    The same check on the same asset, resolving the same way, is one thing that
    happened many times — not many things. Listing each occurrence buries the
    signal that matters, which is how often a given failure repeats.
    """
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    for r in rows:
        key = (r["model"], r["symbol"], r.get("outcome_mode") or "unexplained")
        buckets.setdefault(key, []).append(r)

    out = []
    def _round(xs: list) -> float | None:
        """Mean of the values that exist, rounded. None when there are none.

        Computed once per field: the earlier version called `_mean` twice for
        each — once to test for None and once to round — which is both wasteful
        and a place for the two calls to disagree.
        """
        m = _mean([x for x in xs if x is not None])
        return None if m is None else round(m, 4)

    for (model, symbol, mode), items in buckets.items():
        headline, detail = MISS_PLAIN.get(mode, MISS_PLAIN["unexplained"])
        moves = [i.get("realised_ret") for i in items]
        expected = [i.get("expected_move") for i in items]
        scores = [i.get("score") for i in items]
        side = items[0]["side"]
        against = [(-m if side == "BUY" else m) for m in moves if m is not None]
        out.append({
            "id": f"{model}-{symbol}-{mode}".replace(".", "_"),
            "model": model,
            "model_name": _pretty_model(model),
            "symbol": symbol,
            "avg_score": _round(scores),
            "description": DESCRIPTIONS.get(symbol, ""),
            "outcome": mode,
            "hit": bool(items[0]["hit"]),
            "count": len(items),
            "headline": headline,
            "detail": detail,
            "expected_side": "up" if side == "BUY" else "down",
            "avg_move_pct": _round(moves),
            "avg_expected_pct": _round(expected),
            "avg_against_pct": _round(against),
            "worst_pct": round(max(against), 4) if against else None,
            "first_seen": min(i["created_at"] for i in items)[:10],
            "last_seen": max(i["created_at"] for i in items)[:10],
            "occurrences": [
                {"when": i["created_at"][:10],
                 "moved_pct": round(i["realised_ret"], 4) if i.get("realised_ret") is not None else None,
                 "entry": i.get("entry_price"), "exit": i.get("exit_price")}
                for i in items[:12]
            ],
        })
    return sorted(out, key=lambda e: (-e["count"], e["symbol"]))


def _learning_feed(ledger: ShadowLedger, scan: int = 600) -> list[dict]:
    """Recent checks, grouped by asset and outcome.

    Wins and misses both appear. A feed showing only the wins would be a
    highlight reel, and the point of keeping a ledger is that it is not one.
    """
    groups = _group(ledger.recent(scan))
    for g in groups:
        times = "once" if g["count"] == 1 else f"{g['count']} times"
        verdict = "Worked" if g["hit"] else g["headline"]
        g["brief"] = (f"{g['symbol']} — expected {g['expected_side']}. "
                      f"{verdict}, {times}. Average move "
                      f"{(g['avg_move_pct'] or 0) * 100:+.1f}%.")
    # Strongest suggestions first, not merely most recent. The page is titled
    # "Top suggestions": what leads is the calls the models were most confident
    # in, each shown with what actually happened — a claim next to its outcome
    # is the only format in which confidence means anything.
    groups.sort(key=lambda g: (-(g.get("avg_score") or 0.5),
                               -(g.get("count") or 0)))
    return groups


def _failure_feed(ledger: ShadowLedger, scan: int = 600) -> list[dict]:
    """Only the misses, grouped, with how far off they were on average."""
    groups = _group(ledger.recent(scan, only_misses=True))
    for g in groups:
        times = "once" if g["count"] == 1 else f"{g['count']} times"
        g["brief"] = (f"{g['symbol']} — {g['headline'].lower()}, {times}. "
                      f"Average {(g['avg_against_pct'] or 0) * 100:+.1f}% against us.")
    return groups


def write_export(out: str | Path = "app/data.json", **kwargs) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_export(**kwargs), indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    import sys

    dest = sys.argv[1] if len(sys.argv) > 1 else "app/data.json"
    print(f"wrote {write_export(dest)}")
