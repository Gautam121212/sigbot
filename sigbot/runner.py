"""Daily orchestration.

One entry point per job so cron/systemd stays trivial:
    python -m sigbot.runner daily          # Model B: 24h forecast, fixed universe
    python -m sigbot.runner news           # Model A: news sweep
    python -m sigbot.runner contagion      # Model C: anchor shock -> dependents
    python -m sigbot.runner opportunities  # Model D: unscored thesis digest
    python -m sigbot.runner resolve        # score matured predictions
    python -m sigbot.runner cycle          # resolve, rotate the board, relearn
    python -m sigbot.runner report         # live track record so far
    python -m sigbot.runner publish        # chart the board and rebuild the app

Failure policy is fail-closed: a provider error, a stale bar, or a model that
will not fit produces a HOLD with a stated warning, never a silent guess and
never a signal computed from partial data.
"""
from __future__ import annotations

import functools
import os
import sys
from contextlib import closing
from pathlib import Path
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import (CONTAGION_CANDIDATES, POOL, SETTINGS,
                     UNIVERSE)
from .contagion import ContagionGates, build_network, event_response, gate
from .opportunities import OpportunityModel
from .venture_news import VentureNewsScanner
from .daily_model import DailyModel
from .decide import decide
from .features import build_dataset
from .messenger import ConsoleMessenger, FileMessenger, MultiMessenger, format_daily, format_news
from .providers.market import YahooProvider
from .providers.news import LexiconClassifier, RSSProvider
from .news_model import NewsModel
from .screener import learn_weights, screen, select
from .shadow import ShadowLedger
from .skips import record_skip, report, tracking


def _tracked(operation: str):
    """Reset this operation's skip counts before the job runs.

    Without it, a count from this morning's run is still sitting there tonight
    and the message says a scan failed when it did not.
    """
    def deco(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            with tracking(operation):
                return fn(*a, **kw)
        return inner
    return deco
from .watchlist import Watchlist
from .tiers import render_track_record
from .types import Asset, DailyForecast

MAX_STALE_DAYS = 4


def board_assets(settings=SETTINGS) -> list[Asset]:
    """The assets the models actually run on: the live board, not a fixed list.

    Everything used to iterate UNIVERSE, which meant the board could rotate all
    it liked while the models carried on predicting the same 55 names. The board
    is the source of truth; UNIVERSE is only the fallback for a cold start.
    """
    try:
        wl = Watchlist(settings.watchlist_db)
        held = set(wl.symbols())
    except Exception as exc:  # noqa: BLE001
        # An unreadable board silently switched the models onto the default
        # universe. Same run, different assets, nothing said. Record it.
        record_skip("board_read", settings.watchlist_db, exc)
        held = set()
    if not held:
        return list(UNIVERSE)
    by_symbol = {a.symbol: a for a in POOL}
    return [by_symbol[s] for s in sorted(held) if s in by_symbol]


def board_records(settings=SETTINGS) -> dict[str, tuple[int, float]]:
    """symbol -> (checks, wins) pooled across every model."""
    ledger = ShadowLedger(settings.shadow_db)
    out: dict[str, tuple[int, float]] = {}
    for model in ("news", "daily", "contagion", "opportunity"):
        for sym, (n, rate, _lo) in ledger.stats(model).items():
            pn, ph = out.get(sym, (0, 0.0))
            out[sym] = (pn + n, ph + rate * n)
    return out


def default_messenger():
    sinks = [ConsoleMessenger(), FileMessenger("outbox.log")]
    # Telegram first: under launchd there is no terminal, so console and file
    # are places nobody looks. Every job used to write only to those.
    try:
        from .messenger import TelegramMessenger

        sinks.append(TelegramMessenger())
    except RuntimeError as exc:
        record_skip("delivery_setup", "telegram", exc)
    try:
        from .messenger import WebhookMessenger

        sinks.append(WebhookMessenger())
    except RuntimeError:  # handled: optional sink; the others still work
        pass
    return MultiMessenger(*sinks)


def forecast_asset(asset: Asset, market, settings=SETTINGS) -> DailyForecast | None:
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    df = market.history(asset.symbol, settings.history_start, end)
    warnings: list[str] = []

    last_bar = pd.Timestamp(df.index[-1])
    # Timestamp.utcnow() is deprecated in pandas 3 and printed a warning for
    # every asset on the board — eighty lines of noise per run.
    staleness = (pd.Timestamp.now("UTC").tz_localize(None) - last_bar).days
    if staleness > MAX_STALE_DAYS:
        warnings.append(f"last bar is {staleness} days old — data may be stale")

    ds = build_dataset(df)
    train = ds.iloc[-(settings.train_window + 1) : -1]  # drop final row: its label is the future
    live = ds.iloc[[-1]]

    model = DailyModel().fit(train)
    p_up = float(model.predict_proba(live)[0])
    up_lo, dn_lo, n_bin = model.bin_bounds(p_up)
    exp_move, q10, q90 = model.move_stats(p_up, float(live["vol_20"].iloc[0]))

    d = decide(p_up, up_lo, dn_lo, exp_move, n_bin, model.base_rate,
               settings.gates_for(asset), model.oof_skill)
    if staleness > MAX_STALE_DAYS:
        d = type(d)("HOLD", [], d.blocked_by + ["stale data"])

    return DailyForecast(
        asset=asset, as_of=last_bar, last_close=float(df["close"].iloc[-1]),
        p_up=p_up, p_up_lower=up_lo,
        expected_move_pct=exp_move, q10_pct=q10, q90_pct=q90,
        side=d.side, reasons=d.reasons or d.blocked_by,
        n_calib_bin=n_bin, warnings=warnings,
    )


def run_daily(messenger=None, market=None, settings=SETTINGS) -> None:
    messenger = messenger or default_messenger()
    market = market or YahooProvider()
    ledger = ShadowLedger(settings.shadow_db)
    live = ledger.stats("daily")

    header = [f"Daily 24h outlook — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"]
    body, failures, holds = [], [], 0

    for asset in board_assets(settings):
        try:
            f = forecast_asset(asset, market, settings)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not kill the run  # handled: collected into `failures` and printed in the header
            failures.append(f"{asset.symbol}: {type(exc).__name__}: {exc}")
            continue
        if f is None:
            continue
        # Record every forecast, alert on the few that clear the gates.
        #
        # This used to skip HOLDs entirely, which threw away 98 of 100
        # measurable predictions a day. At that rate an asset needed decades to
        # accumulate the checks a tier requires — the learning loop was real and
        # fed almost nothing. A HOLD still has a direction and still gets
        # checked against what happened; it just never becomes a message.
        direction = "BUY" if f.p_up >= 0.5 else "SELL"
        ledger.record("daily", asset.symbol,
                      f.side if f.side != "HOLD" else direction,
                      f.p_up_lower, f.expected_move_pct, f.last_close, 24,
                      alerted=f.side != "HOLD")
        if f.side == "HOLD":
            holds += 1
            continue
        body.append(format_daily(f, live.get(asset.symbol)))

    ledger.log_run("daily", considered=len(UNIVERSE) if not body else len(body) + holds,
                   signals=len(body),
                   note=f"{holds} holds, {len(failures)} failed to load")
    if not body:
        header.append(f"No signal cleared the gates today ({holds} holds). "
                      "That is the expected outcome most days.")
    if failures:
        header.append(f"{len(failures)} symbol(s) failed: " + "; ".join(failures[:3]))

    messenger.send("\n\n".join(header + body))


def run_news(messenger=None, settings=SETTINGS, hours: int = 12) -> None:
    messenger = messenger or default_messenger()
    ledger = ShadowLedger(settings.shadow_db)
    provider = RSSProvider()
    # The board plus everything the scanner found. Matching only against the
    # board meant a story about a company you do not hold was read, scored, and
    # thrown away — most of what thirty-nine feeds carry, discarded before it
    # was looked at. A story about an asset you could hold is worth scoring
    # even when you do not.
    #
    # These are recorded like any other forecast, so an off-board name that
    # keeps being right builds a record the screen can act on at the next
    # cycle. That is the loop the board rotation was always meant to close.
    universe = list(board_assets(settings))
    on_board = {a.symbol for a in universe}
    try:
        scanned, _note = _load_universe()
        if scanned:
            # Real Asset objects, not the loader's plain rows. The matcher
            # calls asset.match_terms(), and a SimpleNamespace without it
            # crashed the whole news job — the widening shipped without ever
            # running the code path it widened.
            from .types import Asset

            universe += [Asset(symbol=row.symbol,
                               name=getattr(row, "name", "") or row.symbol,
                               kind=getattr(row, "kind", "equity"))
                         for row in scanned if row.symbol not in on_board]
    except Exception as exc:  # noqa: BLE001
        record_skip("news", "universe", exc)

    model = NewsModel(universe, LexiconClassifier(),
                      settings.news_score_threshold)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = provider.fetch(since)
    signals = model.scan(articles, stats=ledger.stats("news"))

    ledger.log_run("news", considered=len(articles), signals=len(signals),
                   note=f"{len(model.universe) if hasattr(model, 'universe') else 0} matchable names")
    if not signals:
        messenger.send(f"News sweep {datetime.now(timezone.utc):%H:%M UTC}: "
                       f"{len(articles)} articles, nothing above threshold.")
        return

    # An entry price, or the forecast can never be scored: `run_resolve` skips
    # every row where entry is None, so news signals were recorded and then
    # sat unresolvable forever. That is why the news model reads "0 checked"
    # after a week of firing — not because nothing cleared the threshold, but
    # because nothing it recorded could ever come due.
    prices: dict[str, float] = {}
    # Not `provider` — that name already holds the RSS feed reader in this
    # function, and rebinding it would break the sweep on the next call.
    market = YahooProvider()
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    for s in signals:
        symbol = s.asset.symbol
        if symbol not in prices:
            try:
                bars = market.history(symbol, settings.history_start, end)
                prices[symbol] = float(bars["close"].iloc[-1])
            except Exception as exc:  # noqa: BLE001
                record_skip("news_price", symbol, exc)
                prices[symbol] = float("nan")
        entry = prices[symbol]
        if entry != entry:                      # NaN: no price, so no forecast
            continue
        ledger.record("news", symbol, s.side, s.raw_score, None, entry, 24)
    messenger.send("\n\n".join(format_news(s) for s in signals))


def run_contagion(messenger=None, market=None, settings=SETTINGS,
                  sigma: float = 2.0, alpha: float = 0.10) -> None:
    """Model C. Screens the network, then alerts on anchors that shocked today.

    The screen is rebuilt each run rather than cached: relationships decay, and
    a stale network is worse than none because it looks authoritative.
    """
    import numpy as np

    messenger = messenger or default_messenger()
    market = market or YahooProvider()
    ledger = ShadowLedger(settings.shadow_db)

    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    anchors = [a.symbol for a in board_assets(settings)]
    returns: dict[str, pd.Series] = {}
    for sym in sorted(set(anchors + CONTAGION_CANDIDATES)):
        try:
            returns[sym] = np.log(
                market.history(sym, settings.history_start, end)["close"]
            ).diff().dropna()
        except Exception as exc:  # noqa: BLE001
            record_skip("contagion", sym, exc)

    anchors = [a for a in anchors if a in returns]
    candidates = [c for c in CONTAGION_CANDIDATES if c in returns]
    links = build_network(returns, anchors, candidates, alpha=alpha)
    survivors = [lk for lk in links if lk.tradeable]
    # A run that finds nothing must still be visible as a run. Three of five
    # model pages read "nothing checked yet" with no way to tell an idle model
    # from a dead one — the only difference between those two is a heartbeat.
    ledger.log_run("contagion", considered=len(links), signals=len(survivors))

    if not survivors:
        messenger.send(
            f"Contagion scan {datetime.now(timezone.utc):%Y-%m-%d}: "
            f"{len(links)} pairs tested, no lagged relationship survived FDR correction. "
            "Same-day co-movement is large but not actionable."
        )
        return

    gates = ContagionGates()
    out: list[str] = []
    skipped: list[str] = []
    for lk in survivors:
        anchor_r = returns[lk.anchor]
        vol = anchor_r.rolling(60).std().shift(1)
        z = float(anchor_r.iloc[-1] / vol.iloc[-1]) if np.isfinite(vol.iloc[-1]) else 0.0
        if abs(z) < sigma:
            continue  # anchor did not shock today; nothing to say

        resp = event_response(anchor_r, returns[lk.dependent],
                              lk.anchor, lk.dependent, sigma=sigma)
        if resp is None:
            continue
        ok, blocked = gate(resp, lk, gates)
        if not ok:
            # Say why. A link that silently vanishes looks identical to one that
            # was never found, and the two need different responses from you.
            skipped.append(f"{lk.dependent} after {lk.anchor}: {'; '.join(blocked)}")
            continue

        side = "BUY" if (resp.mean_response * np.sign(z)) > 0 else "SELL"
        expected = resp.mean_response * np.sign(z)
        try:
            price = float(market.history(lk.dependent, settings.history_start, end)
                          ["close"].iloc[-1])
        except Exception:  # handled: the price is optional; absence is visible downstream
            price = None
        ledger.record("contagion", lk.dependent, side, resp.hit_lower, expected, price, 24)
        out.append(
            f"{'▲' if side == 'BUY' else '▼'} {lk.dependent} — {side}\n"
            f"Affected by: {lk.anchor} ({z:+.1f}σ move today)\n"
            f"Expected 24h response: {expected:+.2%} "
            f"(10–90% {resp.q10:+.2%} to {resp.q90:+.2%})\n"
            f"Score: {resp.hit_lower:.0%} — direction hit rate {resp.hit_rate:.0%} "
            f"over {resp.n_events} historical shocks, base rate {resp.base_hit_rate:.0%}\n"
            f"Link strength: next-day beta {lk.beta_lagged:+.3f}, q={lk.q_lagged:.3f}"
        )

    if not out:
        detail = ("" if not skipped else
                  "\n\nLinks that fired but did not clear the gates:\n  "
                  + "\n  ".join(skipped[:5]))
        messenger.send(
            f"Contagion scan: {len(survivors)} live link(s), but nothing cleared "
            f"the {sigma:g}σ trigger and the gates today.{detail}"
        )
    else:
        messenger.send("\n\n".join(
            [f"Contagion alerts — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"] + out))


_OPPORTUNITY_LOG = Path(".seen_opportunities")
_OPPORTUNITY_KEEP = 400


def _opportunity_key(item) -> str:
    """Stable identifier for a thesis or candidate."""
    import hashlib

    for attr in ("uid", "headline", "title", "thesis", "name"):
        value = getattr(item, attr, None)
        if value:
            return hashlib.sha256(str(value).encode()).hexdigest()[:16]
    return hashlib.sha256(repr(item).encode()).hexdigest()[:16]


def _opportunity_seen(item) -> bool:
    if not _OPPORTUNITY_LOG.exists():
        return False
    return _opportunity_key(item) in _OPPORTUNITY_LOG.read_text().split()


def _opportunity_mark(item) -> None:
    seen = (_OPPORTUNITY_LOG.read_text().split()
            if _OPPORTUNITY_LOG.exists() else [])
    seen.append(_opportunity_key(item))
    # Bounded, so the file cannot grow without limit over months of running.
    _OPPORTUNITY_LOG.write_text("\n".join(seen[-_OPPORTUNITY_KEEP:]))


def _write_opportunity_store(cards, candidates, listings=None,
                             path: str = "opportunities.json") -> None:
    """Persist the plain cards so the report can show them.

    The whole scan is written, not only the new items — the app should show
    what is currently live, whereas the message shows what changed.
    """
    import json

    from .export_app import build_opportunities

    try:
        rows = build_opportunities(cards, candidates)

        # Drop what has already happened. An idea you cannot act on is not an
        # idea, and leaving it on the page means the Ideas count measures how
        # much news arrived rather than how much is live.
        from types import SimpleNamespace

        from .plain_opportunities import expired

        before = len(rows)
        rows = [r for r in rows
                if not expired(SimpleNamespace(**{k: r.get(k, "") for k in
                                                  ("title", "summary",
                                                   "verdict", "sources")}))]
        if before != len(rows):
            print(f"dropped {before - len(rows)} expired idea(s)")

        # Listings were sent to Telegram and never written here, so an IPO
        # card arrived on your phone and was absent from the page — the two
        # views disagreeing about what exists, which is the failure this store
        # was created to prevent in the first place.
        for card in listings or []:
            window = getattr(card, "window", None)
            rows.append({
                "title": card.name,
                "kind": "New listing",
                "colour": card.colour,
                "verdict": card.verdict,
                "summary": (window.note if window
                            else "No dates read from the coverage."),
                "money": f"{card.scored} of a possible {card.possible} points "
                         "on the ten tests the coverage could answer",
                "answered": [r.question for r in card.results
                             if r.observed and r.favourable][:5],
                "unanswered": [r.question for r in card.results
                               if not r.observed][:5],
                "sources": list(card.sources),
            })

        Path(path).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        record_skip("opportunity_store", path, exc)


def run_opportunities(messenger=None, settings=SETTINGS, hours: int = 24) -> None:
    """Model D plus the venture scanner: unscored thesis cards AND business candidates."""
    messenger = messenger or default_messenger()
    articles = RSSProvider().fetch(datetime.now(timezone.utc) - timedelta(hours=hours))

    cards = OpportunityModel().scan(articles)
    candidates = VentureNewsScanner(min_source_quality=0.5).scan(articles)

    # Send only what has not been sent. News stays in the feed for a day or
    # more, so without this the same thesis arrives every four hours — and a
    # channel that repeats itself stops being read.
    # Store everything found; message only what is new.
    # Listings get their own ten fixed tests. They are scored separately from
    # the venture rubric because the questions are different: a new issue is
    # judged on what the coverage says about the company, not on whether you
    # could build the business yourself.
    listings = []
    try:
        from .listings import from_article

        seen_names = set()
        for article in articles:
            card = from_article(article)
            if card and card.name not in seen_names:
                seen_names.add(card.name)
                listings.append(card)
    except Exception as exc:  # noqa: BLE001
        record_skip("listings", "scan", exc)

    _write_opportunity_store(cards, candidates, listings)
    ShadowLedger(settings.shadow_db).log_run(
        "opportunity", considered=len(articles),
        signals=len(cards) + len(candidates) + len(listings or []))

    fresh_cards = [c for c in cards if not _opportunity_seen(c)]
    fresh_candidates = [c for c in candidates if not _opportunity_seen(c)]

    if not fresh_cards and not fresh_candidates and not [
            x for x in listings if not _opportunity_seen(x)]:
        # Deliberately silent. Six messages a day saying nothing happened is
        # how a channel becomes background noise.
        print(f"opportunity scan: {len(articles)} articles, "
              f"{len(cards) + len(candidates)} match(es), none new")
        return

    from .plain_opportunities import render_plain

    body = render_plain(fresh_cards, fresh_candidates)
    fresh_listings = [x for x in listings if not _opportunity_seen(x)]
    if fresh_listings:
        from .listings import by_urgency

        body += "\n\n" + "\n\n".join(
            x.render_text() for x in by_urgency(fresh_listings)[:3])
        for item in fresh_listings:
            _opportunity_mark(item)

    messenger.send(
        f"Opportunity scan — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n\n"
        + body)
    for marked in list(fresh_cards) + list(fresh_candidates):
        _opportunity_mark(marked)


def _is_crypto15m(ledger, pred_id: int) -> bool:
    """Whether this row belongs to the intraday model.

    `due()` does not return the model name, so the unfiltered pass cannot tell
    which rows it has already handled without asking.
    """
    import sqlite3
    from contextlib import closing

    from .crypto15m import MODEL_NAME

    with closing(sqlite3.connect(ledger.path)) as con:
        row = con.execute("SELECT model FROM predictions WHERE id=?",
                          (pred_id,)).fetchone()
    return bool(row) and row[0] == MODEL_NAME


def run_resolve(market=None, settings=SETTINGS) -> None:
    """Score every prediction whose window has closed, against the source that
    made it.

    Every model used to resolve against Yahoo daily closes. For crypto15m that
    is the wrong source and the wrong horizon at once: the forecast was made
    from a Binance fifteen-minute bar and scored against a Yahoo daily close of
    a symbol Yahoo may not even carry. That is where "APT-USD, average move
    -100.0%" came from — a missing quote read as a price of zero — and where a
    64% move on a one-hour horizon came from.

    A wrong resolution is worse than none: it fills the ledger with outcomes
    that never happened, and every hit rate computed from it is fiction.
    """
    from .crypto15m import MODEL_NAME as CRYPTO15M

    ledger = ShadowLedger(settings.shadow_db)
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    resolved = 0

    def _daily_price(symbol: str) -> float:
        provider = market or YahooProvider()
        bars = provider.history(symbol, settings.history_start, end)
        return float(bars["close"].iloc[-1])

    def _intraday_price(symbol: str) -> float:
        from .providers.binance import BinanceProvider

        start = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        bars = BinanceProvider().history(symbol, start, end, "15m")
        return float(bars["close"].iloc[-1])

    for model_name, price_of in ((CRYPTO15M, _intraday_price),
                                 (None, _daily_price)):
        cache: dict[str, float] = {}
        for pred_id, symbol, _side, entry in ledger.due(model_name):
            if entry is None:
                continue
            # The daily pass must not re-resolve crypto15m rows, which the
            # unfiltered query would happily do.
            if model_name is None and _is_crypto15m(ledger, pred_id):
                continue
            try:
                if symbol not in cache:
                    cache[symbol] = price_of(symbol)
                ledger.resolve(pred_id, cache[symbol])
                resolved += 1
            except Exception as exc:  # noqa: BLE001
                record_skip("resolve", symbol, exc)
    due_total = resolved + report("resolve", 0).skipped
    print(f"resolved {resolved} predictions")
    stale = report("resolve", due_total)
    if stale.skipped:
        # Unresolved predictions stay unresolved and keep skewing nothing — but
        # you should know the ledger is not keeping up with what it promised.
        print(stale.line())


UNIVERSE_FILE = "universe.json"
UNIVERSE_MAX_AGE_DAYS = 30


def _load_universe(path: str = UNIVERSE_FILE):
    """The scanned pool, if one exists and is not stale.

    Without this the weekly cycle screens the hardcoded 156 forever and the
    scanned pool is a one-off nobody remembers to re-run. With it, the wider
    pool is what the board is actually drawn from week after week.

    Staleness matters: companies list and delist. A pool built in January and
    still used in June quietly stops containing anything new, and the screen
    reports that nothing better exists — which is a statement about the file,
    not about the market.
    """
    import json
    from types import SimpleNamespace

    file = Path(path)
    if not file.exists():
        return None, ""
    age_days = (datetime.now(timezone.utc).timestamp()
                - file.stat().st_mtime) / 86400
    try:
        rows = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        record_skip("universe", path, exc)
        return None, f"{path} could not be read ({type(exc).__name__})"
    if not rows:
        return None, f"{path} is empty"

    note = ""
    if age_days > UNIVERSE_MAX_AGE_DAYS:
        note = (f"{path} is {age_days:.0f} days old. Listings change; refresh "
                "it with `python scripts/check_universe.py --write` or the "
                "screen is choosing from a stale market.")
    return [SimpleNamespace(symbol=r["symbol"], kind=r["kind"],
                            name=r.get("name", ""))
            for r in rows], note


def _refresh_universe(path: str = UNIVERSE_FILE,
                      max_age_days: int = UNIVERSE_MAX_AGE_DAYS) -> bool:
    """Rebuild the candidate pool if it is missing or stale.

    A failure leaves the existing file in place. Replacing a working pool with
    a half-fetched one would be worse than using a slightly old one: the screen
    would report that nothing better exists, meaning only that fewer things
    were offered.
    """
    import json

    file = Path(path)
    if file.exists():
        age = (datetime.now(timezone.utc).timestamp() - file.stat().st_mtime) / 86400
        if age <= max_age_days:
            return False

    try:
        from .providers.scanner import build

        universe = build()
        if not universe.candidates:
            record_skip("universe", path,
                        RuntimeError("every listing source failed; keeping the "
                                     "existing pool rather than emptying it"))
            return False
        file.write_text(json.dumps(
            [{"symbol": c.symbol, "name": c.name, "kind": c.kind,
              "exchange": c.exchange, "market_cap": c.market_cap,
              "volume": c.volume} for c in universe.candidates], indent=1),
            encoding="utf-8")
        print(f"Refreshed the candidate pool: {len(universe.candidates)} names.")
        for source, reason in universe.failures.items():
            print(f"  {source} did not answer — {reason}")
        return True
    except Exception as exc:  # noqa: BLE001
        record_skip("universe", path, exc)
        return False


CRYPTO15M_PAIRS = int(os.environ.get("SIGBOT_CRYPTO_PAIRS", "100"))


def run_crypto15m(messenger=None, settings=SETTINGS,
                  pairs: int = CRYPTO15M_PAIRS) -> None:
    """Model E. The daily model's machinery on fifteen-minute crypto bars.

    Recorded under its own model name, so tiers, progress and the board treat
    it exactly like the others without a line of special-casing — and so its
    record can never be pooled with the daily model's, which would mix two
    different horizons into one hit rate.

    A hundred pairs is a choice, not a limit: Binance allows a thousand bars a
    request and does not charge, so the cost of widening is download time
    rather than quota. Set SIGBOT_CRYPTO_PAIRS to change it.

    Widening does not multiply the evidence the way the count suggests. A
    hundred pairs on one day still observes one day, and on a day the whole
    market moves together they are closer to one observation than a hundred.
    What it does buy is breadth: a thin pair and a deep one fail differently,
    and only one of those failures is informative.
    """
    from .crypto15m import HORIZON_BARS, MODEL_NAME, forecast, summarise
    from .providers.binance import BinanceProvider, liquid_pairs

    messenger = messenger or default_messenger()
    ledger = ShadowLedger(settings.shadow_db)
    provider = BinanceProvider()

    try:
        symbols = liquid_pairs(pairs)
    except Exception as exc:  # noqa: BLE001
        record_skip("crypto15m", "pairs", exc)
        print(f"could not list pairs: {type(exc).__name__}: {exc}")
        return

    end = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime("%Y-%m-%d")
    # Ten days is ~960 fifteen-minute bars: one Binance request per pair, and
    # comfortably more than the 400 the model needs to fit. Forty-five days was
    # five requests per pair, re-downloading the same history every quarter
    # hour — five hundred calls a run at a hundred pairs, which eventually
    # overruns the window on a slow day and then alerts as a failure.
    start = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")

    out = []
    for symbol in symbols:
        try:
            bars = provider.history(symbol, start, end, "15m")
        except Exception as exc:  # noqa: BLE001
            record_skip("crypto15m", symbol, exc)
            continue
        result = forecast(symbol, bars)
        if result is None:
            record_skip("crypto15m", symbol,
                        RuntimeError("not enough history to fit"))
            continue
        out.append(result)
        # Every forecast is recorded, tradeable or not. Recording only the
        # tradeable ones would make the hit rate a measure of the gate rather
        # than of the model.
        ledger.record(MODEL_NAME, symbol, result.side, result.score,
                      result.expected_move, result.entry,
                      # Four fifteen-minute bars is one hour. The ledger keeps
                      # whole hours, which is the finest resolution the
                      # existing resolver works in — so the horizon is rounded
                      # up rather than silently truncated to zero.
                      horizon_hours=max(1, round(HORIZON_BARS * 0.25)))

    ledger.log_run(MODEL_NAME, considered=len(symbols),
                   signals=sum(1 for f in out if f.tradeable),
                   note=f"{len(out)} scored")
    print(summarise(out))


def run_cycle(messenger=None, market=None, settings=SETTINGS,
              rescreen: bool = False) -> None:
    """Close the loop: resolve, rotate, relearn, rebuild.

    Run this nightly after the collectors. It is the only command that changes
    the board, and it changes it by at most two names — the rest of the time it
    reports that nothing had enough evidence to move, which is the honest
    outcome for the first several months.
    """
    messenger = messenger or default_messenger()
    market = market or YahooProvider()
    lines: list[str] = [f"Cycle — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"]

    # 1. Score anything whose window has closed. Records must be current before
    #    any decision reads them.
    try:
        run_resolve(market, settings)
    except Exception as exc:  # noqa: BLE001  # handled: counted by report('cycle_screen') and printed
        lines.append(f"resolve failed: {type(exc).__name__}: {exc}")

    records = board_records(settings)
    checked = sum(n for n, _ in records.values())
    lines.append(f"{checked:,} checks on record across {len(records)} assets.")

    # 2. Rotate. At most two leave, and only on a record thick enough to mean it.
    wl = Watchlist(settings.watchlist_db)
    if not wl.symbols():
        wl.seed(POOL)
        lines.append(f"Board seeded to {len(wl.symbols())}.")

    # Rebuild the pool before screening if it has gone stale. Three HTTP
    # requests, so it is cheap; leaving it to a command you must remember is
    # how the wider pool becomes a one-off.
    _refresh_universe()

    candidates = POOL
    scanned, universe_note = _load_universe()
    if scanned:
        candidates = scanned
        print(f"Screening {len(candidates)} scanned candidates rather than the "
              f"built-in {len(POOL)}.")
    if universe_note:
        print(universe_note)
        record_skip("universe", UNIVERSE_FILE, RuntimeError(universe_note))
    if rescreen:
        try:
            bars, kinds = {}, {}
            end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
            for a in candidates:
                try:
                    bars[a.symbol] = market.history(a.symbol, settings.history_start, end)
                    kinds[a.symbol] = a.kind
                except Exception as exc:  # noqa: BLE001
                    record_skip("cycle_screen", a.symbol, exc)
            loaded = report("cycle_screen", len(candidates))
            if loaded.skipped:
                print(loaded.line())
            results = screen(bars, kinds,
                             anchors=[a.symbol for a in board_assets(settings)][:20],
                             records=records)
            weights, note = learn_weights(results, records)
            lines.append(note)
            ranked = select(screen(bars, kinds, records=records, weights=weights), 100)
            candidates = [type("A", (), {"symbol": r.symbol, "kind": r.kind})()
                          for r in ranked]
        except Exception as exc:  # noqa: BLE001  # handled: traceback printed by the job wrapper
            lines.append(f"screen skipped: {type(exc).__name__}: {exc}")

    result = wl.rotate(records, candidates)
    if result["dropped"]:
        for d in result["dropped"]:
            lines.append(f"dropped {d['symbol']} — {d['reason']}")
        lines.append(f"replaced with {result['added']}; board at {result['size']}.")
    else:
        lines.append("No asset had a record bad enough to drop. Nothing moved.")
    lines.append(result["note"])
    messenger.send("\n".join(lines))


@_tracked("publish")
def _report_fingerprint(path: str) -> str:
    """Digest of the report, ignoring the timestamp.

    Without excluding generated_at every rebuild differs and the change check
    does nothing — which is the failure mode of most "only send if changed"
    implementations.
    """
    import hashlib
    import re

    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?", "", raw)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _read_opportunity_store(path: str = "opportunities.json") -> list[dict]:
    """The cards the opportunity job last found.

    One source of truth for the app and the message. An empty list means the
    scan has not run yet or matched nothing — both are ordinary, and the tab
    says which.
    """
    import json

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        record_skip("opportunity_store", path, exc)
        return []
    return raw if isinstance(raw, list) else []


def _heartbeat_line(settings=SETTINGS) -> str:
    """One line saying the thing is alive and what it currently holds."""
    import sqlite3
    from datetime import datetime, timezone

    board = pending = checked = 0
    unreadable = []
    try:
        with closing(sqlite3.connect(settings.watchlist_db)) as con:
            board = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        # Reporting "board 0" for a database that could not be opened would say
        # the board is empty when it is only unreadable — two different facts.
        record_skip("heartbeat", "watchlist", exc)
        unreadable.append("board")
    try:
        with closing(sqlite3.connect(settings.shadow_db)) as con:
            pending, checked = con.execute(
                "SELECT COUNT(*) - COUNT(hit), COUNT(hit) FROM predictions"
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        record_skip("heartbeat", "ledger", exc)
        unreadable.append("ledger")

    line = (f"alive {datetime.now(timezone.utc):%H:%M UTC} · board {board} · "
            f"{checked} checked, {pending} waiting")
    if unreadable:
        line += f" · could not read: {', '.join(unreadable)}"
    return line


def _send_heartbeat(reason: str, state_path: str = ".last_heartbeat") -> None:
    """A short, silent line saying the system is alive and nothing changed.

    Without this, silence is ambiguous: no message means either "nothing
    happened" or "it has been dead since Tuesday", and nothing on the phone
    tells them apart.

    Silent on purpose. A heartbeat that buzzes 48 times a day is the thing you
    mute, and muting the channel takes the real alerts with it. It also replaces
    the previous heartbeat, so the chat holds one line rather than a wall.
    """
    import os
    import sqlite3
    from datetime import datetime, timezone

    from .setup_delivery import _delete_message, send

    bits = [f"Alive — {datetime.now(timezone.utc):%d %b %H:%M UTC}", reason]
    try:
        with sqlite3.connect(SETTINGS.shadow_db) as con:
            made, checked = con.execute(
                "SELECT COUNT(*), COUNT(hit) FROM predictions").fetchone()
        bits.append(f"{made} predictions made, {checked} checked.")
    except Exception as exc:  # noqa: BLE001
        record_skip("heartbeat", "ledger", exc)
        bits.append("The ledger could not be read, which is worth looking at.")

    marker = Path(state_path)
    previous = None
    if marker.exists():
        try:
            previous = int(marker.read_text().strip())
        except ValueError:  # a corrupt marker must not block the heartbeat
            previous = None

    try:
        result = send(" ".join(bits), silent=True)
    except Exception as exc:  # noqa: BLE001
        record_skip("heartbeat", "telegram", exc)
        return

    if previous:
        token = os.environ.get("TELEGRAM_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if token and chat:
            _delete_message(token, chat, previous)
    message_id = (result.get("result") or {}).get("message_id")
    if message_id:
        marker.write_text(str(message_id))


def _markets_shut(when) -> bool:
    """Whether every equity market is closed. Crypto is deliberately ignored —
    it never closes, so waiting for it means never sending."""
    from .market_hours import Venue, is_open

    return not any(is_open(v, when) for v in (Venue.NSE, Venue.NYSE))


def run_day_summary(settings=SETTINGS, messenger=None, now=None) -> None:
    """One message after the last session closes, summarising the day.

    Runs hourly and does nothing until two conditions hold: every equity market
    is shut, and it has not already spoken today. An interval alone would drift
    — a 24-hour timer started at 20:00 fires at 20:00, then 20:04, then 20:09,
    and within a fortnight it is reporting mid-session.

    Crypto is deliberately not waited for. It never closes, so waiting for it
    means never sending.
    """
    import sqlite3


    now = now or datetime.now(timezone.utc)
    if not _markets_shut(now):
        return

    marker = Path(".last_day_summary")
    today = now.date().isoformat()
    if marker.exists() and marker.read_text().strip() == today:
        return

    since = (now - timedelta(hours=24)).isoformat()
    lines = [f"Day summary — {now:%A %d %B}"]

    try:
        with sqlite3.connect(settings.shadow_db) as con:
            made = con.execute("SELECT COUNT(*) FROM predictions WHERE created_at>=?",
                               (since,)).fetchone()[0]
            checked, hits = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(hit),0) FROM predictions "
                "WHERE hit IS NOT NULL AND resolve_after>=? AND resolve_after<=?",
                (since, now.isoformat())).fetchone()
            total, total_checked = con.execute(
                "SELECT COUNT(*), COUNT(hit) FROM predictions").fetchone()
            causes = con.execute(
                "SELECT outcome_mode, COUNT(*) FROM predictions WHERE hit=0 "
                "AND outcome_mode IS NOT NULL AND resolve_after>=? "
                "GROUP BY outcome_mode ORDER BY 2 DESC", (since,)).fetchall()
    except Exception as exc:  # noqa: BLE001
        record_skip("day_summary", "ledger", exc)
        lines.append("The ledger could not be read, which is itself worth looking at.")
        made = checked = hits = total = total_checked = 0
        causes = []

    lines.append(f"\nMade {made} forecast(s). {checked} came due; "
                 f"{hits} were right.")
    if checked:
        from .stats import wilson_interval

        lo, _ = wilson_interval(hits, checked, 0.90)
        lines.append(f"That is {hits / checked:.0%} on the day, worst case "
                     f"{lo:.0%} — a single day is far too few to mean anything, "
                     "and is shown because hiding it would be worse.")
    if causes:
        lines.append("\nWhere it went wrong:")
        lines += [f"  {m.replace('_', ' ')}: {c}" for m, c in causes[:4]]

    lines.append(f"\nAll time: {total} made, {total_checked} checked.")

    # How far off a verdict is. Without this the summary says the same thing
    # every night for months and gives no way to tell accumulation from a
    # stalled ledger.
    try:
        from .progress import measure

        for model in measure(settings.shadow_db).models:
            if model.days_to_verdict:
                lines.append(f"  {model.name}: about {model.days_to_verdict} "
                             f"day(s) until there is enough to judge.")
            elif model.colour == "#8b8b9a":
                lines.append(f"  {model.name}: STALLED — nothing recorded "
                             "lately, which is a fault, not a quiet market.")
    except Exception as exc:  # noqa: BLE001
        record_skip("day_summary", "progress", exc)

    try:
        with sqlite3.connect(settings.watchlist_db) as con:
            board = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
            dropped = con.execute(
                "SELECT symbol FROM graveyard WHERE dropped_at>=?", (since,)).fetchall()
        note = f"\nBoard: {board} assets."
        if dropped:
            note += " Replaced today: " + ", ".join(d[0] for d in dropped[:4]) + "."
        lines.append(note)
    except Exception as exc:  # noqa: BLE001
        record_skip("day_summary", "watchlist", exc)

    gaps = report("scheduler", 0)
    if gaps.skipped:
        lines.append(f"\n{gaps.skipped} task failure(s) today. A quiet stretch "
                     "caused by that is not a quiet market.")

    (messenger or default_messenger()).send("\n".join(lines))
    marker.write_text(today)
    print("day summary sent")


def _green_count(path: str = "app/data.json") -> int:
    """How many models have earned the right to alert.

    Read from the export rather than recomputed, so the number in the message
    is the number on the page. Recomputing would let the two disagree.
    """
    import json

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # handled: no export yet means nothing is green
        return 0
    return sum(1 for m in data.get("models", [])
               if str(m.get("tier", "")).lower() in ("trade", "green", "alert"))


def run_publish(settings=SETTINGS, market=None, days: int = 180) -> None:
    """Draw a chart for every asset on the board, then write the app files.

    Charts are rendered for the whole board rather than a subset. They are SVG
    paths, so the cost is file size rather than anything that degrades — and a
    board where only some names have charts is a board you stop trusting.
    """
    from .chart_svg import chart_block  # noqa: F401  (import checked early)
    from .export_app import build_charts, write_export
    from .report import write_report

    market = market or YahooProvider()
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    # Stocks only. Crypto has its own model on its own clock; forecasting a
    # coin here as well would double-count it — two records for one asset,
    # each too thin to mean anything, at two horizons neither page explains.
    assets = [a for a in board_assets(settings) if a.kind != "crypto"]
    bars, kinds = {}, {}
    for a in assets:
        try:
            bars[a.symbol] = market.history(a.symbol, settings.history_start, end)
            kinds[a.symbol] = a.kind
        except Exception as exc:  # noqa: BLE001
            record_skip("publish", a.symbol, exc)

    missing = report("publish", len(assets))
    if missing.skipped:
        print(missing.line())
    charts = build_charts(bars, kinds, days=days)
    # The Ideas tab needs the last scan's output. Without this it renders
    # empty forever while Telegram receives the cards — the same information
    # arriving in one place and not the other.
    ideas = []
    try:
        # Read what the opportunity job found. Rescanning here was wrong: two
        # fetches minutes apart return different articles, so the message could
        # carry two cards while the app rendered an empty tab — the same event
        # with two answers and nothing on screen explaining the difference.
        ideas = _read_opportunity_store()
    except Exception as exc:  # noqa: BLE001
        record_skip("publish_ideas", "store", exc)

    write_export("app/data.json", db_path=settings.shadow_db,
                 watchlist_path=settings.watchlist_db, charts=charts,
                 opportunities=ideas)
    out = write_report("app/data.json", "app/sigbot-report.html")

    # Push it, replacing the one it supersedes. A file already in the chat is a
    # frozen copy: it shows whatever was true when it was sent, and nothing on
    # screen says otherwise. Keeping one means whatever you tap is current.
    try:
        from .setup_delivery import send_report

        fingerprint = _report_fingerprint(str(out))
        marker_file = Path(".last_report_hash")
        previous = marker_file.read_text().strip() if marker_file.exists() else ""

        # A heartbeat every run, whether or not the report changed. Silence is
        # otherwise ambiguous: no message means either nothing changed or it
        # broke, and nothing on screen tells you which.
        try:
            from .setup_delivery import send_heartbeat

            send_heartbeat(_heartbeat_line(settings))
        except Exception as exc:  # noqa: BLE001
            record_skip("heartbeat", "telegram", exc)

        # A new green is always worth sending, even if the fingerprint
        # matched — a model crossing its threshold is the event this whole
        # system exists to catch, and suppressing it to save bandwidth would
        # be the wrong trade.
        greens = _green_count()
        green_marker = Path(".last_green_count")
        was = int(green_marker.read_text().strip()) if green_marker.exists() else 0
        green_marker.write_text(str(greens))
        new_green = greens > was

        if fingerprint == previous and not new_green:
            print("report unchanged since the last send — not resending "
                  "(the copy on your phone is still current)")
            _send_heartbeat("Nothing changed since the last report, so the file "
                            "on your phone is still current.")
        else:
            stamp = datetime.now(timezone.utc).strftime("%d %b %H:%M UTC")
            caption = (f"NEW GREEN — {greens} model(s) now alertable — {stamp}"
                       if new_green else f"Board — {stamp}")
            # The deploy copy lives in its own folder. Writing it to
            # app/index.html overwrote the standalone template that
            # build_standalone reads — a generated artifact clobbering a
            # source file, found by the template's own guard test. app/public/
            # holds only generated output; point Cloudflare at that.
            public = out.parent / "public"
            public.mkdir(exist_ok=True)
            (public / "index.html").write_bytes(out.read_bytes())
            # One deployable file. The telegram-named copy is deleted after
            # sending (or immediately when telegram is unconfigured) so app/
            # holds exactly one page and there is nothing to pick wrongly.
            send_report(str(out), caption=caption)
            # Report size from the surviving copy — the working file is
            # deleted next, and stat() after unlink was a crash shipped by
            # cleaning up in the wrong order.
            out.unlink(missing_ok=True)
            marker_file.write_text(fingerprint)
            print("report sent, previous one removed")
    except Exception as exc:  # noqa: BLE001
        record_skip("report_delivery", "telegram", exc)
        print(f"report not sent: {type(exc).__name__}: {exc}")
    print(f"{len(charts)} of {len(assets)} board assets charted")
    survivor = out.parent / "public" / "index.html"
    shown = survivor if survivor.exists() else out
    print(f"wrote {shown} ({shown.stat().st_size / 1024:.0f} KB)")


def run_report(settings=SETTINGS) -> None:
    """Track record by evidence tier. No schedule, no projection, no target.

    Tier is earned by the resolved record. Nothing here can promote an asset
    early, and nothing lowers a threshold to make a tier reachable.
    """
    ledger = ShadowLedger(settings.shadow_db)
    for model in ("daily", "news", "contagion"):
        n, hit, lo = ledger.overall(model)
        if n == 0:
            print(f"\n=== {model} ===\nno resolved predictions yet")
            continue
        print(f"\n=== {model} ===")
        print(f"overall: {n} resolved, hit rate {hit:.1%}, 90% lower bound {lo:.1%}")
        modes = ledger.failure_modes(model)
        if modes:
            print("outcomes: " + ", ".join(
                f"{k} {v}" for k, v in sorted(modes.items(), key=lambda kv: -kv[1])))
        per = ledger.stats(model)
        ranked = sorted(per.items(), key=lambda kv: -kv[1][0])[:10]
        for symbol, (cnt, rate, _lower) in ranked:
            print("  " + render_track_record(
                symbol, model, cnt, rate * cnt,
                ledger.failure_modes(model, symbol)).replace("\n", "\n  "))


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "daily"
    jobs: dict[str, Callable[[], None]] = {
        "daily": run_daily,
        "news": run_news,
        "contagion": run_contagion,
        "opportunities": run_opportunities,
        "resolve": run_resolve,
        "cycle": run_cycle,
        "report": run_report,
        "publish": run_publish,
        "day_summary": run_day_summary,
        "crypto15m": run_crypto15m,
    }
    if cmd not in jobs:
        print(f"usage: python -m sigbot.runner [{'|'.join(jobs)}]")
        return 2
    try:
        jobs[cmd]()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
