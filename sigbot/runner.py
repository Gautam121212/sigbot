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

import re
import sqlite3

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


def board_assets(settings=SETTINGS) -> list:
    """Every tradable asset — no 100-name ceiling.

    This used to return the 100-row watchlist, and nine jobs drew from it, so
    every model was confined to the same hundred names however wide the market
    was. The watchlist now only decides what the site highlights; it no longer
    limits what gets looked at.

    The pool is the scanned universe (universe.json) merged with the built-in
    list, de-duplicated by symbol. The built-in list is kept so a missing or
    unreadable universe file degrades to the old coverage instead of to none.
    """
    seen: dict[str, object] = {}
    # Names that returned no price history at all in the last 30 days are
    # skipped. The universe widened from 100 names to 675 and includes
    # delisted ones; fetching them every day spent time and returned nothing.
    dead = _dead_symbols()
    loaded, note = _load_universe()
    if note:
        record_skip("universe", UNIVERSE_FILE, RuntimeError(note))
    # The curated list FIRST. It carries short names and aliases ("reliance",
    # "ril"); the scanned universe carries legal names. Loading the universe
    # first let its entries replace the curated ones for every name on both
    # lists — and the news matcher lost the names headlines actually use.
    for asset in list(POOL) + list(loaded or []):
        sym = getattr(asset, "symbol", None)
        if sym and sym not in seen and not _is_dead(sym, dead):
            seen[sym] = asset
    return list(seen.values()) or list(UNIVERSE)


DEAD_FILE = "dead_symbols.json"
DEAD_RETRY_DAYS = 30


def _dead_symbols(path: str = DEAD_FILE) -> dict[str, str]:
    """symbol -> ISO date it last returned no price history at all."""
    import json
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _mark_dead(symbol: str, path: str = DEAD_FILE) -> None:
    """Remember a name that returned NO history, so it is not fetched daily.

    Only an empty history counts. A short one is a new listing, not a dead
    one, and treating it as dead would hide exactly the names a wide scan
    exists to find.
    """
    import json
    dead = _dead_symbols(path)
    dead[symbol] = datetime.now(timezone.utc).date().isoformat()
    try:
        Path(path).write_text(json.dumps(dead, indent=1, sort_keys=True),
                              encoding="utf-8")
    except OSError as exc:
        record_skip("dead_symbols", symbol, exc)


def _is_dead(symbol: str, dead: dict[str, str]) -> bool:
    """Dead if it returned nothing within the last 30 days. After that it is
    tried again, because a suspended stock can resume trading."""
    seen = dead.get(symbol)
    if not seen:
        return False
    try:
        age = (datetime.now(timezone.utc).date()
               - datetime.fromisoformat(seen).date()).days
    except ValueError:
        return False
    return age < DEAD_RETRY_DAYS


SECTORS_FILE = "sectors.json"
# At most this many new sector look-ups a run: each is a network call, and a
# crash day can fire on hundreds of names.
SECTOR_LOOKUPS_PER_RUN = 40
_sector_lookups = {"n": 0}


def _sector_of(symbol: str, lookup=None) -> str:
    """The stock's sector, looked up once and remembered.

    Assets carried no sector at all, so every name fell into "unknown" and the
    rule "at most two positions per sector" was really "at most two trades a
    day". Sectors are fetched only for names about to be traded, cached in a
    committed file so the GitHub runs share it, and "unknown" stays a single
    shared bucket — the cautious direction when a correlation cannot be seen.
    """
    import json as _json
    path = Path(SECTORS_FILE)
    try:
        cache = _json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        cache = {}
    if symbol in cache:
        return cache[symbol] or "unknown"
    if _sector_lookups["n"] >= SECTOR_LOOKUPS_PER_RUN:
        return "unknown"
    _sector_lookups["n"] += 1
    sector = ""
    try:
        if lookup is not None:
            sector = lookup(symbol) or ""
        else:
            import yfinance as yf
            sector = (yf.Ticker(symbol).info or {}).get("sector") or ""
    except Exception as exc:  # noqa: BLE001  # handled: recorded; the name stays "unknown", the cautious bucket
        record_skip("sectors", symbol, exc)
    cache[symbol] = sector
    try:
        path.write_text(_json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        record_skip("sectors", "cache", exc)
    return sector or "unknown"


def _open_book(ledger) -> tuple[int, dict[str, int]]:
    """Stocks positions still open: taken, not yet resolved — with sectors.

    Each daily run started from an empty book, so the six-position and
    two-per-sector limits applied only within one day's trades. With holds of
    ten and sixty days, positions from earlier runs must count.
    """
    import json as _json
    with closing(sqlite3.connect(ledger.path)) as con:
        rows = con.execute("SELECT payload FROM predictions WHERE model='stocks' "
                           "AND hit IS NULL").fetchall()
    n = 0
    sectors: dict[str, int] = {}
    for (payload,) in rows:
        try:
            info = _json.loads(payload) if payload else {}
        except (TypeError, ValueError):
            info = {}
        if info.get("taken"):
            n += 1
            sec = info.get("sector") or "unknown"
            sectors[sec] = sectors.get(sec, 0) + 1
    return n, sectors


def market_regime(closes) -> str | None:
    """"up" or "down" (index vs its 200-day average) / "calm" or "volatile"
    (20-day volatility vs its own long-run median) — the split under which
    oversold signals stopped flipping sign between periods."""
    if len(closes) < 260:
        return None
    rets = closes.pct_change().dropna()
    vol20 = rets.rolling(20).std().dropna()
    trend = "up" if closes.iloc[-1] > closes.tail(200).mean() else "down"
    mood = "volatile" if vol20.iloc[-1] > vol20.median() else "calm"
    return f"{trend}/{mood}"


# Core-and-satellite. Idle capital is held in the index; the satellite takes
# only setups that ADD return beyond it over the same days. Measured: the
# dip-buying school added +0.56% a trade since 2016 (t 4.0) and +0.44% on
# 2009-15 (t 2.5); momentum added nothing.
#
# REGIME-SWITCHING (round 4): momentum is admitted too, because its setup now
# fires only in calm uptrends, where it added return beyond the index in all
# three periods. Each school trades only in the regime where it was positive
# every time: momentum in calm rises, capitulation in volatile declines.
SATELLITE_STYLES = frozenset({"reversion", "momentum"})

# The leaders' sectors, in Yahoo's naming. Fixed and well known, so written
# down rather than looked up.
LEADER_SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AVGO": "Technology", "AMD": "Technology", "ORCL": "Technology",
    "CRM": "Technology", "INTC": "Technology", "QCOM": "Technology",
    "AMZN": "Consumer Cyclical", "TSLA": "Consumer Cyclical",
    "GOOGL": "Communication Services", "META": "Communication Services",
    "NFLX": "Communication Services", "JPM": "Financial Services",
    "GS": "Financial Services", "V": "Financial Services", "XOM": "Energy",
    "UNH": "Healthcare", "LLY": "Healthcare", "WMT": "Consumer Defensive",
    "COST": "Consumer Defensive", "BA": "Industrials", "CAT": "Industrials",
}

LEADER_DROP = -0.04        # a leader falling this much in a day...
FOLLOWER_DROP = -0.03      # ...and a same-sector name falling this much too
REBOUND_HOLD_DAYS = 5

# The old follow-on bet — follow the leader's direction — lost on 745,570
# cases: the sector slightly REVERSED the next day (-0.21%), hard in the 2020
# crash (-1.11%). It is switched off; the rebound below replaces it.
LEGACY_FOLLOW = False


def sympathy_rebounds(today: dict[str, float], sector_of=None) -> list[tuple[str, str]]:
    """(follower, leader) pairs to buy for the rebound after a leader falls.

    today: symbol -> today's simple return.

    Measured on liquid US stocks: after a leader fell 4%+, same-sector names
    that also fell 3%+ returned +0.52% over five days since 2016 and +1.61%
    on 2009-15 — a period never used to choose it, and stronger there, the
    opposite of an overfitted rule. Quick sympathy moves tend to fade; this
    buys the fade. Caveat: many names fire on the same few days, so the
    independent evidence is closer to the number of such days than to the
    number of trades.
    """
    sector_of = sector_of or _sector_of
    hit_sectors = {LEADER_SECTORS[L]: L for L, r in today.items()
                   if L in LEADER_SECTORS and r <= LEADER_DROP}
    if not hit_sectors:
        return []
    out = []
    for sym, r in sorted(today.items(), key=lambda kv: kv[1]):
        if sym in LEADER_SECTORS or r > FOLLOWER_DROP:
            continue
        sec = sector_of(sym)
        if sec in hit_sectors:
            out.append((sym, hit_sectors[sec]))
    return out


def display_assets(settings=SETTINGS) -> list:
    """The names the SITE draws — the highlighted board, not the whole pool.

    `board_assets` answers "what may the models look at?" and now returns all
    675 tradable assets. Publish used the same function to decide what to
    CHART, so removing the 100-name ceiling from the models also removed it
    from the page: 606 charts, and a page that grew from about 2 MB to 17 MB —
    slow on a phone, larger with every name added, and heading for Cloudflare's
    25 MB file limit. Two different questions, so two functions.

    Falls back to the old built-in universe when the watchlist is empty, so a
    fresh install still draws something.
    """
    try:
        held = set(Watchlist(settings.watchlist_db).symbols())
    except Exception as exc:  # noqa: BLE001
        record_skip("display", settings.watchlist_db, exc)
        held = set()
    pool = {a.symbol: a for a in board_assets(settings)}
    if not held:
        return list(UNIVERSE)
    return [pool[s] for s in sorted(held) if s in pool]


# Large-cap leaders used as ANCHORS for follow-on moves. A professional reads
# follow-on moves as leaders dragging their suppliers, customers and peers —
# big names moving small ones — not as every stock predicting every other. It
# also bounds the work: anchors x followers stays linear in the universe
# instead of quadratic, so the whole pool can be followers.
LEADERS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "JPM", "XOM", "UNH", "LLY", "V", "WMT", "COST", "AMD",
    "NFLX", "ORCL", "CRM", "BA", "CAT", "GS", "INTC", "QCOM",
)


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


LEARN_LOG = "learning_log.jsonl"
LEARN_LOG_MAX = 3000

# Every headline fetched, with its timestamp and the gate's verdict. This is
# the news archive the model has never had: a record of what was known and
# when, to be matched later against what prices did. Bounded so the file
# cannot grow without limit in the repository.
NEWS_ARCHIVE = "news_archive.jsonl"
NEWS_ARCHIVE_MAX = 20000


def _news_provider():
    """The RSS feeds plus GDELT. Either can fail without stopping the other."""
    from .providers.gdelt import CombinedNewsProvider
    from .providers.gkg import GKGProvider

    # GDELT through its bulk files, not its search API: the API refused every
    # request, and its own refusal message tells heavy users to use the bulk
    # datasets. The files are static downloads with no request quota.
    return CombinedNewsProvider([RSSProvider(), GKGProvider()])


def _source_records(ledger) -> dict[str, tuple[int, float, float]]:
    """source -> (checks, hit rate, chance rate) for news, from the payload.

    News predictions recorded no source until the intake gate, so this starts
    empty and fills as scored predictions accumulate. A source is judged only
    once it has enough checks (see intake.SOURCE_MIN_CHECKS).
    """
    import json as _json
    from collections import defaultdict

    with closing(sqlite3.connect(ledger.path)) as con:
        rows = con.execute("SELECT payload, hit FROM predictions WHERE model='news' "
                           "AND hit IS NOT NULL AND payload != ''").fetchall()
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for payload, hit in rows:
        try:
            src = (_json.loads(payload) or {}).get("source")
        except (TypeError, ValueError):
            src = None
        if src:
            tally[src][0] += 1
            tally[src][1] += int(bool(hit))
    n_all = sum(v[0] for v in tally.values())
    chance = (sum(v[1] for v in tally.values()) / n_all) if n_all else 0.5
    return {k: (v[0], v[1] / v[0], chance) for k, v in tally.items() if v[0]}


def _gate_articles(articles, assets, ledger, job: str):
    """ACT, LEARN and DROP, as the intake gate decides.

    Returns (act, learn). LEARN items are appended to the learning log with
    their event class and instruments, so their market reaction can be
    studied later; they are never traded on. DROP items are only counted.
    """
    import json as _json
    from collections import Counter

    from .intake import ACT, LEARN, judge, matches_tradable

    records = _source_records(ledger)
    verdicts: list[str] = []
    act: list = []
    learn: list = []
    tally: Counter[str] = Counter()
    for a in articles:
        d = judge(a.title, a.summary, tradable=matches_tradable(a.title, assets),
                  source_record=records.get(a.source))
        tally[d.verdict] += 1
        verdicts.append(d.verdict)
        if d.verdict == ACT:
            act.append(a)
        elif d.verdict == LEARN:
            learn.append((a, d))
    try:
        arch = Path(NEWS_ARCHIVE)
        seen_urls: set[str] = set()
        old_lines = arch.read_text(encoding="utf-8").splitlines() if arch.exists() else []
        for line in old_lines[-NEWS_ARCHIVE_MAX:]:
            try:
                seen_urls.add(_json.loads(line).get("url", ""))
            except ValueError:
                continue
        verdict_of = {id(a): v for a, v in zip(articles, verdicts)}
        new_lines = [_json.dumps({
            "at": a.published_at.isoformat(), "title": a.title, "url": a.url,
            "source": a.source, "verdict": verdict_of.get(id(a))})
            for a in articles if a.url and a.url not in seen_urls]
        if new_lines:
            arch.write_text("\n".join((old_lines + new_lines)[-NEWS_ARCHIVE_MAX:]) + "\n",
                            encoding="utf-8")
    except OSError as exc:
        record_skip(job, "news_archive", exc)
    if learn:
        try:
            path = Path(LEARN_LOG)
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            lines += [_json.dumps({
                "at": a.published_at.isoformat(), "job": job, "title": a.title,
                "url": a.url, "source": a.source, "class": d.event_class,
                "instruments": list(d.instruments), "why": d.reason})
                for a, d in learn]
            path.write_text("\n".join(lines[-LEARN_LOG_MAX:]) + "\n", encoding="utf-8")
        except OSError as exc:
            record_skip(job, "learning_log", exc)
    print(f"intake: {tally.get(ACT, 0)} act, {tally.get(LEARN, 0)} learn, "
          f"{tally.get('DROP', 0)} dropped of {len(articles)}")
    return act, [a for a, _d in learn]


def run_news(messenger=None, settings=SETTINGS, hours: int = 12) -> None:
    messenger = messenger or default_messenger()
    ledger = ShadowLedger(settings.shadow_db)
    provider = _news_provider()
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
    fetched = provider.fetch(since)
    # Only material, new, tradable stories reach the model. Recaps of moves
    # already made are in the price by definition, and scoring them taught the
    # model from noise; material events with nothing to trade go to the
    # learning log instead.
    articles, _learn = _gate_articles(fetched, universe, ledger, "news")
    signals = model.scan(articles, stats=ledger.stats("news"))

    ledger.log_run("news", considered=len(fetched), signals=len(signals),
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
        # The source travels with the forecast, so each source builds a
        # record and the intake gate can stop trusting the ones that are
        # reliably wrong.
        import json as _json
        src = s.articles[0].source if s.articles else ""
        ledger.record("news", symbol, s.side, s.raw_score, None, entry, 24,
                      payload=_json.dumps({"source": src}))
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

    anchors = list(LEADERS)
    followers = sorted({a.symbol for a in board_assets(settings)
                        if getattr(a, "kind", "") == "equity"} | set(CONTAGION_CANDIDATES))
    returns: dict[str, pd.Series] = {}
    for sym in sorted(set(anchors) | set(followers)):
        try:
            returns[sym] = np.log(
                market.history(sym, settings.history_start, end)["close"]
            ).diff().dropna()
        except Exception as exc:  # noqa: BLE001
            record_skip("contagion", sym, exc)

    anchors = [a for a in anchors if a in returns]
    candidates = [c for c in followers if c in returns and c not in anchors]

    # The rebound: recorded as the follow-on model's forecasts, held five
    # trading days, before the old lead-lag logic (now off) is reached.
    import json as _json
    today = {sym: float(np.expm1(r.iloc[-1])) for sym, r in returns.items()
             if len(r)}
    rebound = sympathy_rebounds(today)
    for sym, leader in rebound:
        try:
            rebound_price = float(market.history(sym, settings.history_start, end)["close"].iloc[-1])
        except Exception as exc:  # noqa: BLE001  # handled: recorded; no price, no forecast
            record_skip("contagion", sym, exc)
            continue
        ledger.record("contagion", sym, "BUY", 0.6, abs(today[sym]), rebound_price,
                      REBOUND_HOLD_DAYS * 24 * 7 // 5,
                      payload=_json.dumps({"setup": "sympathy-rebound",
                                           "leader": leader}))
    if rebound:
        messenger.send(f"Follow-on rebound {datetime.now(timezone.utc):%Y-%m-%d}: "
                       + ", ".join(f"{s} after {lead}" for s, lead in rebound[:12]))
    if not LEGACY_FOLLOW:
        ledger.log_run("contagion", considered=len(candidates),
                       signals=len(rebound), note="sympathy rebound")
        return
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
    recorded = 0
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

        # TWO GATES, DIFFERENT JOBS.
        #
        # Recording and alerting were the same decision, so a link that failed
        # the alert bar was never written down — and this model finished its
        # first month with ONE resolved check out of 17,583 firings. It could
        # not learn because it refused to observe.
        #
        # Every triggered link is now recorded and scored like any other
        # forecast. Only gated ones are alerted. The recording gate is
        # permissive on purpose: an observation costs nothing and is the only
        # way to find out whether the alert gate is set anywhere near right.
        side = "BUY" if (resp.mean_response * np.sign(z)) > 0 else "SELL"
        expected = resp.mean_response * np.sign(z)
        try:
            price = float(market.history(lk.dependent, settings.history_start, end)
                          ["close"].iloc[-1])
        except Exception:  # handled: the price is optional; absence is visible downstream
            price = None
        ledger.record("contagion", lk.dependent, side, resp.hit_lower, expected,
                      price, 24)
        recorded += 1

        if not ok:
            # Say why. A link that silently vanishes looks identical to one that
            # was never found, and the two need different responses from you.
            skipped.append(f"{lk.dependent} after {lk.anchor}: {'; '.join(blocked)}")
            continue

        out.append(
            f"{'▲' if side == 'BUY' else '▼'} {lk.dependent} — {side}\n"
            f"Affected by: {lk.anchor} ({z:+.1f}σ move today)\n"
            f"Expected 24h response: {expected:+.2%} "
            f"(10–90% {resp.q10:+.2%} to {resp.q90:+.2%})\n"
            f"Score: {resp.hit_lower:.0%} — direction hit rate {resp.hit_rate:.0%} "
            f"over {resp.n_events} historical shocks, base rate {resp.base_hit_rate:.0%}\n"
            f"Link strength: next-day beta {lk.beta_lagged:+.3f}, q={lk.q_lagged:.3f}"
        )

    if recorded:
        messenger.send(
            f"Contagion recorded {recorded} triggered link(s) for scoring; "
            f"{len(out)} cleared the alert bar. Recording is deliberately "
            "looser than alerting — a link has to be observed before anyone "
            "can tell whether the alert bar is set anywhere near right.")

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
    fetched = _news_provider().fetch(datetime.now(timezone.utc) - timedelta(hours=hours))
    # Opportunities keep ACT and LEARN — both are worth a person's attention —
    # and lose only the recaps and noise.
    act, learn = _gate_articles(fetched, list(board_assets(settings)),
                                ShadowLedger(settings.shadow_db), "opportunities")
    articles = act + learn

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
    _resolve_reasons: dict[str, str] = {}

    ledger = ShadowLedger(settings.shadow_db)
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    resolved = 0

    bars_cache: dict[str, object] = {}

    def _daily_bars(symbol: str):
        if symbol not in bars_cache:
            provider = market or YahooProvider()
            bars_cache[symbol] = provider.history(symbol, settings.history_start, end)
        return bars_cache[symbol]

    def _daily_price(symbol: str) -> float:
        return float(_daily_bars(symbol)["close"].iloc[-1])

    def _stopped_price(pred_id: int, entry: float, side: str) -> float | None:
        """The stop price if a stocks trade was stopped out, else None.

        Resolution used to score every trade at the latest close and never
        looked at what happened on the way. That made the live system a fixed
        clock, whatever the exit plan said — and the exit plan was the single
        largest measured improvement: +0.759% a trade on the clock against
        +1.424% with the ATR stop, on the same 9,246 historical entries.

        Only the stocks model records a real stop distance, so only it is
        checked. Every other model resolves exactly as before.
        """
        plan = ledger.stop_plan(pred_id)
        if plan is None:
            return None
        model, created_at, stop_distance = plan
        if model not in ("stocks",) or stop_distance < 0.005:
            return None
        bars = _daily_bars(symbol_of[pred_id])
        after = bars[bars.index.astype(str).str[:10] > created_at[:10]]
        if after.empty or "low" not in after or "high" not in after:
            return None
        if side.upper() == "SELL":
            stop = entry * (1.0 + stop_distance)
            return stop if float(after["high"].max()) >= stop else None
        stop = entry * (1.0 - stop_distance)
        return stop if float(after["low"].min()) <= stop else None

    symbol_of: dict[int, str] = {}

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
                exit_price = cache[symbol]
                if model_name is None:
                    symbol_of[pred_id] = symbol
                    stopped = _stopped_price(pred_id, float(entry), _side)
                    if stopped is not None:
                        # Stopped out on the way: the loss is the planned one,
                        # not whatever the close happened to be at the horizon.
                        exit_price = stopped
                ledger.resolve(pred_id, exit_price)
                resolved += 1
            except Exception as exc:  # noqa: BLE001
                record_skip("resolve", symbol, exc)
                # First failure of each kind is printed, so a live GitHub run
                # names WHY prices could not be fetched (Binance 451 from a US
                # host, Yahoo rate-limit, delisting) instead of only counting.
                key = f"{'crypto' if model_name else 'daily'}:{type(exc).__name__}"
                if key not in _resolve_reasons:
                    _resolve_reasons[key] = str(exc)[:120]
    due_total = resolved + report("resolve", 0).skipped
    print(f"resolved {resolved} predictions")
    if _resolve_reasons:
        print("  price fetch failures (first of each kind):")
        for key, msg in _resolve_reasons.items():
            print(f"    {key}: {msg}")
    stale = report("resolve", due_total)
    if stale.skipped:
        # Unresolved predictions stay unresolved and keep skewing nothing — but
        # you should know the ledger is not keeping up with what it promised.
        print(stale.line())


UNIVERSE_FILE = "universe.json"
UNIVERSE_MAX_AGE_DAYS = 30


# Legal suffixes stripped to find the name a headline actually uses.
_LEGAL = re.compile(
    r"\b(common stock|ordinary shares?|american depositary shares?|adr|"
    r"class [a-c]|series [a-c]|inc\.?|incorporated|corporation|corp\.?|"
    r"company|co\.?|ltd\.?|limited|plc|holdings?|group|n\.?v\.?|s\.?a\.?|"
    r"ag|se|l\.?p\.?|llc|the)\b", re.IGNORECASE)

# One-word names that are also ordinary words. "Target" would match every
# "price target"; these rely on their ticker instead.
_AMBIGUOUS = frozenset({
    "target", "gap", "block", "square", "match", "general", "american",
    "first", "united", "national", "global", "international", "energy",
    "capital", "financial", "digital", "health", "power", "best", "live",
    "news", "fox", "chart", "trade", "market", "street", "royal", "state",
    "union", "pacific", "southern", "northern", "western", "eastern",
})


def _common_names(legal: str) -> tuple[str, ...]:
    """The name headlines use, from a legal name.

    "Apple Inc. Common Stock" -> ("apple",). Universe rows carry legal names,
    and a headline never says "Apple Inc. Common Stock" — so without this the
    news matcher could not recognise any of the 600 widened names by name.
    """
    cleaned = _LEGAL.sub(" ", legal or "")
    cleaned = re.sub(r"[^A-Za-z0-9&' -]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    if len(cleaned) < 4 or cleaned in _AMBIGUOUS:
        return ()
    return (cleaned,)


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
    # Real Asset objects, not bare namespaces. The news matcher calls
    # asset.match_terms(), and a namespace without it crashed the whole news
    # job the first time the universe was widened — and the same crash was
    # about to ship again when the 100-name board was removed, because the
    # conversion lived in one caller rather than here at the source.
    del SimpleNamespace
    return [Asset(symbol=r["symbol"], name=r.get("name") or r["symbol"],
                  kind=r.get("kind", "equity"),
                  aliases=_common_names(r.get("name") or ""))
            for r in rows if r.get("symbol")], note


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

    # The monthly review runs with the weekly cycle. It only reports, so a
    # failure here must never undo the cycle that has already run.
    try:
        run_review(settings)
    except Exception as exc:  # noqa: BLE001  # handled: recorded; the cycle's work stands
        record_skip("cycle_review", "alignment", exc)


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


# Tracking belongs on the job, not on a helper inside it. It sat on
# _report_fingerprint, which runs partway through publishing, so it reset the
# publish failure counts mid-run — while run_publish itself was untracked and
# carried stale counts from one run into the next.
@_tracked("publish")
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
    assets = [a for a in display_assets(settings) if a.kind != "crypto"]
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


def run_backtest(symbols: list[str] | None = None,
                 settings=SETTINGS) -> None:
    """Score the daily model against history instead of waiting for the future.

    The walk-forward engine already existed and was only reachable from the
    screener, so a month of live checks was the only way to judge an idea.
    This exposes it: same rules (chronological only, refit on a trailing
    window, costs charged on every signal, compared against baselines), run
    across the board and pooled into one readable answer.

    Results are NOT written to the shadow ledger. A replayed result is a
    hypothesis about data the model may have been shaped on; a live result is
    evidence. Mixing them is how a system starts lying about itself.
    """
    from .backtest import walk_forward
    from .features import build_dataset

    market = YahooProvider()
    assets = [a for a in board_assets(settings) if a.kind != "crypto"]
    if symbols:
        wanted = {s.upper() for s in symbols}
        assets = [a for a in assets if a.symbol.upper() in wanted]

    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    results, skipped = [], []
    for asset in assets:
        try:
            bars = market.history(asset.symbol, settings.history_start, end)
            res = walk_forward(build_dataset(bars), symbol=asset.symbol)
        except Exception as exc:  # noqa: BLE001
            record_skip("backtest", asset.symbol, exc)
            skipped.append(asset.symbol)
            continue
        if res.n_predictions:
            results.append(res)
        else:
            skipped.append(asset.symbol)

    print(_backtest_summary(results, skipped))


def _backtest_summary(results, skipped) -> str:
    """Pool the per-symbol results into one answer, with its caveats.

    Pooled on purpose: a table of forty decisions per symbol invites reading
    the best column, which is the commonest way a backtest flatters itself.
    """
    if not results:
        return ("Backtest produced no decisions. Every symbol either had too "
                "little history for the training window or failed to fetch — "
                f"{len(skipped)} skipped. That is a result about the data, "
                "not about the model.")

    total = sum(r.n_predictions for r in results)
    signals = sum(r.n_signals for r in results)
    acc = sum(r.directional_accuracy * r.n_predictions
              for r in results) / total
    base = sum(r.base_rate * r.n_predictions for r in results) / total
    skill = sum((r.brier_baseline - r.brier) * r.n_predictions
                for r in results) / total

    lines = [f"Backtest — daily model over {len(results)} symbol(s)", ""]
    lines.append(f"  Decisions replayed     {total:,}")
    lines.append(f"  Directional accuracy   {acc:.1%}")
    lines.append(f"  Base rate (up days)    {base:.1%}")
    lines.append(f"  Edge over base         {(acc - base) * 100:+.1f} points")
    lines.append(f"  Brier skill vs base    {skill:+.4f}")
    lines.append(f"  Signals that fired     {signals:,}")
    if skipped:
        lines.append(f"  Skipped                {len(skipped):,} symbol(s)")
    lines.append("")
    if acc - base > 0.02 and skill > 0:
        lines.append("  Beats its baseline on history. That makes it worth "
                     "running forward — it is not evidence that it works.")
    else:
        lines.append("  Does not beat its baseline on history. Running it "
                     "forward would most likely reproduce that, and the live "
                     "record so far agrees.")
    lines.append("  Three caveats. The symbol list is the current board, so "
                 "anything delisted or already dropped is missing and the "
                 "number is flattered by its absence. The model may have been "
                 "shaped on this same history. And nothing here is written to "
                 "the ledger: a replay is a hypothesis, a live check is "
                 "evidence.")
    return "\n".join(lines)


def run_reset(settings=SETTINGS, full: bool = False) -> None:
    """Clear what is genuinely wrong, keep what is genuinely evidence.

    A record collected under a mis-set gate is not contaminated. The hit
    definition never changed, the entry and exit prices are real, and the
    scoring was correct — what was wrong was the BAR those results were judged
    against, which is a display decision applied at read time. Deleting them
    would destroy thousands of valid scored predictions to fix a number that
    is already fixed.

    What IS invalid is a row recording the wrong kind of thing. The daily
    model forecast crypto until B27 restricted it to stocks, and those rows
    describe a model that no longer exists. They go.

    `full=True` clears every prediction, for when a genuinely fresh start is
    wanted. It is not the default because it costs weeks of real evidence and
    the learning loop is not confused by correct data.
    """
    import os
    import shutil
    import sqlite3
    from contextlib import closing
    from datetime import datetime, timezone

    # A full wipe destroys weeks of evidence that cannot be recreated, so it
    # does not happen on a typo. This guard exists because a TEST of this
    # function wiped the real ledger: dataclass field defaults are evaluated
    # once at import, so a monkeypatched SIGBOT_DB never reached a freshly
    # constructed settings object and the delete ran against the live file.
    if full and os.environ.get("SIGBOT_CONFIRM_RESET") != "yes":
        print("Refusing to wipe the ledger.\n"
              "  This deletes every prediction and cannot be undone.\n"
              "  Back it up first:  cp shadow.db shadow-backup.db\n"
              "  Then re-run with:  SIGBOT_CONFIRM_RESET=yes "
              "python -m sigbot.runner reset-all")
        return

    with closing(sqlite3.connect(settings.shadow_db)) as con:
        before = con.execute(
            "SELECT COUNT(*) FROM predictions").fetchone()[0]

    # Snapshot before any destructive write, always. Cheap insurance against
    # the exact accident described above.
    if before:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = f"{settings.shadow_db}.{stamp}.bak"
        shutil.copy(settings.shadow_db, backup)
        print(f"Backed up to {backup} before touching anything.")

    with closing(sqlite3.connect(settings.shadow_db)) as con:
        if full:
            con.execute("DELETE FROM predictions")
            con.execute("DELETE FROM runs")
            note = "every prediction and run"
        else:
            # Frozen rows: exit price identical to entry, meaning no new bar
            # was ever read. A zero move cannot clear the cost bar, so each
            # was scored an automatic miss — 47% of the daily record. They are
            # unscored here rather than deleted: the forecast was real and can
            # be resolved properly once a genuine bar exists.
            con.execute(
                "UPDATE predictions SET exit_price=NULL, realised_ret=NULL, "
                "hit=NULL, outcome_mode=NULL "
                "WHERE hit IS NOT NULL AND entry_price IS NOT NULL "
                "AND exit_price = entry_price")

            # Category error: daily never should have forecast crypto.
            con.execute("DELETE FROM predictions "
                        "WHERE model='daily' AND symbol LIKE '%-USD'")
            # A single row cannot teach anything and predates the two-gate
            # split that will now produce thousands.
            con.execute("DELETE FROM predictions WHERE model='contagion'")
            note = "daily's crypto rows and contagion's pre-split row"
        con.commit()
        after = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]

    print(f"Cleared {note}: {before - after:,} row(s) removed, "
          f"{after:,} kept.")
    if not full:
        print("Kept on purpose: every correctly-scored prediction. The gate "
              "that misjudged them is fixed and applies at read time, so the "
              "record itself was never wrong.")
    print("paper.json and the site rebuild from the ledger, so both follow "
          "automatically on the next publish.")


def run_setups(settings=SETTINGS) -> None:
    """Scan the board for validated setups and record what fires.

    Records a forecast ONLY when a setup fires. That is the whole change from
    the old daily model: it had an opinion on every asset every session and
    scored 51.4% against a 52.2% base across 141,123 replayed decisions. This
    will produce a few hundred forecasts a year and each one carries a
    measured, out-of-sample-validated reason.
    """
    from datetime import datetime, timedelta, timezone

    from .personality import profile_from_closes
    from .setups import context_multiplier, evaluate
    from .shadow import ShadowLedger

    ledger = ShadowLedger(settings.shadow_db)
    market = YahooProvider()
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    fired, looked, skipped = [], 0, 0
    for asset in [a for a in board_assets(settings) if a.kind != "crypto"]:
        try:
            bars = market.history(asset.symbol, settings.history_start, end)
            from .features import _mfi, _rsi
            rsi = float(_rsi(bars["close"]).iloc[-1])
            mfi = float(_mfi(bars).iloc[-1])
            close = float(bars["close"].iloc[-1])
        except Exception as exc:  # noqa: BLE001
            record_skip("setups", asset.symbol, exc)
            skipped += 1
            continue

        looked += 1
        closes = [float(x) for x in bars["close"].tolist() if x and x > 0]
        profile = profile_from_closes(asset.symbol, closes)

        row = {"rsi_14": rsi, "mfi_14": mfi, "close": close}
        for col, key in (("atr_14", "atr_14"), ("volume", "volume")):
            if col in bars:
                row[key] = float(bars[col].iloc[-1])
        if "volume" in bars and len(bars) >= 20:
            row["volume_ma_20"] = float(bars["volume"].tail(20).mean())

        setup = evaluate(row, profile)
        if setup is None:
            continue

        # Context scales the score, never the decision. The strongest context
        # cell held 22 occurrences — enough to lean on, nowhere near enough
        # to gate on.
        weight, why = context_multiplier(row)
        score = min(setup.measured_edge_pp / 100.0 * weight, 0.99)
        ledger.record("setups", asset.symbol, setup.side, score, 0.0, close, 24)
        fired.append(f"{asset.symbol}: {setup.name} (RSI {rsi:.1f}) — {why}")

    ledger.log_run("setups", looked, len(fired), "")
    if fired:
        default_messenger().send("Setups fired:\n  " + "\n  ".join(fired))
        print(f"{len(fired)} setup(s) fired out of {looked} looked at.")
    else:
        print(f"Looked at {looked} asset(s); no validated setup fired. That is "
              "the normal state — the condition is rare on purpose, and "
              "silence costs nothing.")
    if skipped:
        print(f"{skipped} skipped (no price data).")


def run_priority(settings=SETTINGS, budget_minutes: float = 20.0,
                 execute: bool = False) -> None:
    """Run jobs in order of urgency, weighted by what each has proved.

    Shows the queue by default and runs it only with `execute=True`, so the
    plan can be inspected before it spends any time. Verdicts come from the
    same logic as `diagnose`, which means a job's priority falls on its own
    once its record shows it finds nothing — nobody has to remember to demote
    it.
    """
    from .priority import describe, plan

    verdicts = _job_verdicts(settings)
    # resolve runs first EVERY tick so that past-due forecasts are scored
    # before new ones arrive. Without it forecasts pile up indefinitely — the
    # bug that left 1,494 rows unscored despite daily GitHub runs: resolve was
    # in the registry but not in the queue, so priority-run never called it.
    #
    # Stocks, contagion and profiles read daily bars: running them every three
    # hours repeats the same work eight times a day on 675 names. They stay on
    # the weekday daily tick in the workflow (step 4 of WORKFLOW_CHANGE.md).
    jobs = ["resolve", "news", "opportunity", "crypto15m"]
    queue = plan(jobs, verdicts, budget_seconds=budget_minutes * 60)
    print(describe(queue))

    if not execute:
        print("\n  Showing the plan only. Run with execute to act on it.")
        return

    registry = _job_registry()
    missing = [q.job for q in queue if q.runs and q.job not in registry]
    if missing:
        # Loud, not skipped: silently passing over a planned job is how the
        # first version reported running news while never running it.
        print(f"\n  NOT RUN — no runner registered for: {', '.join(missing)}")
    for slot in queue:
        if not slot.runs:
            continue
        fn = registry.get(slot.job)
        if fn is None:
            continue
        try:
            fn()
        except Exception as exc:  # noqa: BLE001  # handled: recorded and the queue carries on
            record_skip("priority", slot.job, exc)
            print(f"  {slot.job} failed ({type(exc).__name__}); moving on.")


def _job_verdicts(settings=SETTINGS) -> dict[str, str]:
    """Each model's one-word verdict, as `diagnose` would give it.

    Duplicates diagnose's classification rather than parsing its printed
    output, because a priority decision that depends on the wording of a
    report would break the first time the report is rephrased.
    """
    import sqlite3
    from contextlib import closing

    from .export_app import TARGET_CHECKS
    from .shadow import ShadowLedger
    from .stats import wilson_interval

    ledger = ShadowLedger(settings.shadow_db)
    out: dict[str, str] = {}
    try:
        with closing(sqlite3.connect(settings.shadow_db)) as con:
            for model in TARGET_CHECKS:
                resolved, hits = con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(hit),0) FROM predictions "
                    "WHERE model=? AND hit IS NOT NULL", (model,)).fetchone()
                recorded = con.execute(
                    "SELECT COUNT(*) FROM predictions WHERE model=?",
                    (model,)).fetchone()[0]
                if not recorded:
                    out[model] = "NO DATA"
                elif resolved < TARGET_CHECKS[model] * 0.5:
                    out[model] = "TOO EARLY"
                else:
                    lower, _ = wilson_interval(hits, resolved, 0.90)
                    out[model] = ("NO EDGE" if lower <= ledger.empirical_null(model)
                                  else "WORKING")
    except Exception as exc:  # noqa: BLE001  # handled: unknown verdicts default to full priority
        record_skip("priority", "verdicts", exc)
    return out


def _job_registry() -> dict:
    """Every job the priority queue can run, keyed by the name it plans with.

    The first version held three entries, so execute mode silently skipped
    news — the most urgent job on the queue. A planner whose top priority
    cannot run is worse than no planner, because it reports the right thing
    happening.

    It also briefly contained `priority` ITSELF: an edit adding priority to
    the main job table matched an identical line in here too, and execute
    mode would have called the queue recursively. The registry is now built
    explicitly and a test forbids any entry that runs the scheduler.

    Keys are the PLANNING names. The model is `opportunity` and its job is
    `opportunities`, and that kind of mismatch fails silently in a dict.
    """
    registry = {
        "resolve": lambda: run_resolve(YahooProvider(), SETTINGS),
        "news": run_news,
        "contagion": run_contagion,
        "opportunity": run_opportunities,
        "stocks": run_stocks,
        "crypto15m": run_crypto15m,
        "profiles": run_profiles,
    }
    thematic = globals().get("run_thematic")
    if thematic is not None:
        registry["thematic"] = thematic
    return registry


def run_review(settings=SETTINGS) -> None:
    """The monthly review: live behaviour measured against the playbook."""
    from .alignment import describe, record_history
    from .alignment import run_review as _review
    from .risk import LOSS_STREAK_PAUSE
    from .shadow import ShadowLedger

    considered, recorded, _alerted = ShadowLedger(settings.shadow_db).selectivity("stocks")
    checks, setups = _review(settings.shadow_db, considered, recorded,
                             LOSS_STREAK_PAUSE)
    print(describe(checks, setups))
    from .calibration import check as _gaps
    from .calibration import describe as _describe_gaps
    print()
    print(_describe_gaps(_gaps(settings.shadow_db)))
    try:
        record_history(checks, setups)
    except Exception as exc:  # noqa: BLE001  # handled: the review still printed; only the history write is lost
        record_skip("review", "history", exc)


def gather_promotion_evidence(settings=SETTINGS):
    """Everything the promotion ladder judges, from the real records."""
    from .alignment import DRIFT, _stocks_trades, monthly_returns
    from .alignment import run_review as _review
    from .benchmarks import ACCOUNT_NET_MONTH, HOLD_INDEX, SATELLITE_OOS
    from .paper import replay
    from .promotion import Evidence
    from .risk import LOSS_STREAK_PAUSE

    ledger = ShadowLedger(settings.shadow_db)
    considered, recorded, _alerted = ledger.selectivity("stocks")
    checks, _setups = _review(settings.shadow_db, considered, recorded,
                              LOSS_STREAK_PAUSE)
    r_values = [t["r"] for t in _stocks_trades(settings.shadow_db)
                if t["r"] is not None]
    months = [r for _k, r in monthly_returns(settings.shadow_db)]
    book = replay(settings.shadow_db, models={"stocks"})
    return Evidence(
        # Core-and-satellite: the account is the index plus what the
        # dip-buying satellite adds, after costs and the survivorship haircut.
        hist_net_month=ACCOUNT_NET_MONTH,
        index_month=HOLD_INDEX.avg_month,
        oos_net_month=SATELLITE_OOS.monthly_alpha(),
        paper_r=r_values,
        paper_months=months,
        paper_drawdown=float(getattr(book, "max_drawdown", 0.0) or 0.0),
        review_drifts=sum(c.verdict == DRIFT for c in checks),
    )


def run_promotion(settings=SETTINGS) -> None:
    """Which stage the evidence supports, and what blocks the next one."""
    from .benchmarks import EXPECTED
    from .promotion import describe, describe_models, evaluate

    print(describe(evaluate(gather_promotion_evidence(settings),
                            worst_hist_month=EXPECTED.worst_month)))
    print()
    print(describe_models())


SURPRISE_LOOKUPS_PER_RUN = 40


def _earnings_surprise(symbol: str, lookup=None) -> float | None:
    """Surprise (%) of an earnings report in the last three days, or None.

    Only called for stocks that already rose 2%+ beyond the index today —
    a handful a day — so the per-stock look-up stays cheap.
    """
    try:
        if lookup is not None:
            return lookup(symbol)
        import yfinance as yf
        df = yf.Ticker(symbol).get_earnings_dates(limit=4)
        if df is None or df.empty or "Surprise(%)" not in df:
            return None
        now = pd.Timestamp.now(tz="UTC")
        for when, row in df.iterrows():
            ts = pd.Timestamp(when)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            if pd.Timedelta(0) <= now - ts <= pd.Timedelta(days=3):
                val = row.get("Surprise(%)")
                return float(val) if val == val and val is not None else None
    except Exception as exc:  # noqa: BLE001  # handled: recorded; no surprise, no signal
        record_skip("surprise", symbol, exc)
    return None


def record_confirmed_surprises(ledger, candidates, lookup=None) -> int:
    """Paper-record every big beat the market confirmed today.

    candidates: (symbol, close, reaction excess) for stocks up 2%+ beyond the
    index today. Recorded on PAPER ONLY (taken=False) with the 19-day horizon
    the history measured, so the learning loop tracks the edge — +1.20% /
    +0.44% / +1.26% in the three periods — before any capital follows it.
    """
    import json as _json

    from .indicators import DRIFT_DAYS, confirmed_surprise

    n = 0
    for sym, close, reaction in candidates[:SURPRISE_LOOKUPS_PER_RUN]:
        surprise = _earnings_surprise(sym, lookup)
        if not confirmed_surprise(surprise, reaction):
            continue
        ledger.record("stocks", sym, "BUY", 0.6, 0.0, close,
                      DRIFT_DAYS * 24 * 7 // 5,
                      payload=_json.dumps({"setup": "confirmed-surprise",
                                           "taken": False, "surprise": surprise,
                                           "reaction": round(reaction, 4)}))
        n += 1
    return n


def crypto_exposure(index_regime: str | None) -> str:
    """Bitcoin exposure from the STOCK market's regime — the liquidity idea.

    Holding Bitcoin except while stocks are in a volatile decline compounded
    to about x155 over 2016-2026 against x110 for holding, mainly by cutting
    2022 from -76% to -28%. It is not better every year (it missed most of
    2023) and rests on few bear markets, so it advises; it does not trade.
    Unknown regime returns "HOLD" — the default is not to act on no data.
    """
    return "STAND ASIDE" if index_regime == "down/volatile" else "HOLD"


def run_outcomes(settings=SETTINGS) -> None:
    """Old strategy against new, year by year, for every model."""
    from .outcomes import describe
    print(describe())


def run_research(settings=SETTINGS) -> None:
    """The research log: what was tested, how, and what survived."""
    from .research import summary
    print(summary())


def run_events(settings=SETTINGS) -> None:
    """Print what each recorded class of event actually did to each asset."""
    from .events import describe
    print(describe())


def run_stocks(settings=SETTINGS) -> None:
    """Scan the WHOLE universe, record only what fired.

    Deliberately not `board_assets`. Every model ran on the same 100 names,
    which caps learning twice: a setup can only be seen where the board
    happens to look, and the board only rotates on evidence gathered from that
    same narrow window. A scanner that cannot find what it is not watching is
    not a scanner.

    Records both tiers. Risky rows are recorded at a third of normal size
    precisely so they accumulate the live record that would promote or kill
    them — a gate admitting only certainty never validates anything new.
    """
    from datetime import datetime, timedelta, timezone

    from .exits import plan as exit_plan
    from .features import _mfi, _rsi
    from .risk import RiskState, decide
    from .scan import PROVEN, scan_row, summarise
    from .shadow import ShadowLedger

    ledger = ShadowLedger(settings.shadow_db)
    market = YahooProvider()
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    # The whole pool. This iterated UNIVERSE — 55 names — which made the
    # "wide" scan narrower than the 100-name board it was built to replace.
    # Whether the index itself is trending up. Momentum only buys while it is;
    # if the index cannot be read, momentum does not fire at all.
    index_up = None
    index_regime = None
    spy_day: float | None = None
    surprise_candidates: list[tuple[str, float, float]] = []
    try:
        spy = market.history("SPY", settings.history_start, end)["close"]
        if len(spy) >= 200:
            index_up = bool(spy.iloc[-1] > spy.tail(200).mean())
            index_regime = market_regime(spy)
            spy_day = float(spy.iloc[-1] / spy.iloc[-2] - 1)
    except Exception as exc:  # noqa: BLE001  # handled: recorded; regime-gated setups fail closed
        record_skip("stocks", "index-trend", exc)

    universe = [a for a in board_assets(settings)
                if "-USD" not in a.symbol and getattr(a, "kind", "") != "crypto"]
    hits, looked, skipped = [], 0, 0
    refused: list[str] = []
    # The book as the risk rules see it, SEEDED FROM REAL RESULTS.
    #
    # This used to start from RiskState(equity=100_000.0) and never read the
    # ledger, which left three of the five circuit breakers permanently dead:
    # loss_streak was always 0, so the streak pause could never fire; day P&L
    # was always 0, so the daily limit could never fire; peak equity was
    # never set, so the drawdown throttle could never fire. Each was correct,
    # tested, and switched off by the one line that built the state.
    #
    # The streak pause is the rule that mattered most in the historical
    # comparison — trades after four straight losses returned -0.559 R — so
    # a pause that cannot fire was the single most expensive gap in the
    # system.
    state = _seed_risk_state(ledger, settings)
    # Sectors of positions still open from earlier runs, so the per-sector
    # limit counts the real book rather than one day's trades.
    sector_count: dict[str, int] = dict(_open_book(ledger)[1])

    for asset in universe:
        try:
            bars = market.history(asset.symbol, settings.history_start, end)
            if len(bars) == 0:
                _mark_dead(asset.symbol)
                skipped += 1
                continue
            if len(bars) < 200:
                skipped += 1
                continue
            close = float(bars["close"].iloc[-1])
            row = {
                "close": close,
                "prev_close": float(bars["close"].iloc[-2]),
                "rsi_14": float(_rsi(bars["close"]).iloc[-1]),
                "mfi_14": float(_mfi(bars).iloc[-1]),
                "sma_200": float(bars["close"].tail(200).mean()),
                "sma_50": float(bars["close"].tail(50).mean()),
                "index_up": index_up,
                "index_regime": index_regime,
                # The high of the PREVIOUS year, excluding today, so a close
                # at a new high can register as one.
                "hi52": (float(bars["high"].iloc[-253:-1].max())
                         if "high" in bars and len(bars) > 60 else None),
                "willr_14": _williams(bars),
                "atr_14": _atr_last(bars),
                "volume": float(bars["volume"].iloc[-1]) if "volume" in bars else None,
                "volume_ma_20": (float(bars["volume"].tail(20).mean())
                                 if "volume" in bars else None),
            }
        except Exception as exc:  # noqa: BLE001
            record_skip("stocks", asset.symbol, exc)
            skipped += 1
            continue

        looked += 1
        # Candidates for the confirmed-surprise check: up 2%+ beyond the index.
        if spy_day is not None and len(bars) > 1:
            reaction = close / float(bars["close"].iloc[-2]) - 1 - spy_day
            if reaction >= 0.02:
                surprise_candidates.append((asset.symbol, close, reaction))
        hit = scan_row(asset.symbol, row)
        if hit is None:
            continue

        # EVERY firing signal is recorded, whether or not risk lets it be
        # traded. Recording and acting are different decisions — conflating
        # them is the bug that left contagion with one check in its life
        # (B36/B52) and hid 2,680 daily predictions from its own run log
        # (B68). A signal refused on risk grounds is still evidence about the
        # setup, and throwing it away would make the risk rules invisible in
        # the record they distort.
        atr = row.get("atr_14")
        plan = exit_plan(close, float(atr)) if isinstance(atr, (int, float)) and atr else None
        sector = _sector_of(asset.symbol)

        if plan is None:
            refused.append(f"{asset.symbol}: no volatility reading, so no "
                           "stop could be placed")
            decision = None
        elif hit.candidate.style not in SATELLITE_STYLES:
            # Core-and-satellite: idle capital sits in the index. Momentum,
            # measured against the index over the same 60 days, added nothing
            # since 2016 (-0.05%, t -0.2) and lost to it on 2009-15 (-0.83%,
            # t -5.8): its gains were the market's. Taking it would only
            # duplicate the core at extra cost, so it is recorded on paper and
            # never given capital.
            refused.append(f"{asset.symbol}: {hit.candidate.name} duplicates "
                           "the index core — recorded, not taken")
            decision = None
        else:
            decision = decide(
                RiskState(equity=state.equity, open_risk=state.open_risk,
                          deployed=state.deployed,
                          open_positions=state.open_positions,
                          sector_positions=sector_count.get(sector, 0),
                          loss_streak=state.loss_streak,
                          day_pnl_pct=state.day_pnl_pct,
                          peak_equity=state.peak_equity),
                entry_price=close, stop_price=plan.stop_price)
            if not decision.allowed:
                refused.append(f"{asset.symbol}: {decision.reason}")

        # The recorded score is conviction, so the live record can later be
        # split by tier. The exit plan rides along in expected_move, which is
        # what the paper model sizes from.
        # Liquidity travels with the trade so the paper book can charge a
        # realistic cost: daily traded value and daily volatility are the two
        # inputs to the square-root impact estimate.
        import json as _json
        vol_ma = row.get("volume_ma_20") or 0.0
        atr = row.get("atr_14") or 0.0
        liquidity = _json.dumps({
            "adv": round(float(vol_ma) * close, 2) if vol_ma else None,
            "vol": round(float(atr) / close, 6) if atr and close else None,
            # Which setup fired and in which tier, so each one's live record
            # can be compared with what its history promised. Without this the
            # monthly review can only judge the model as a whole, and a setup
            # quietly decaying would be averaged away by one that works.
            "setup": hit.candidate.name,
            "style": hit.candidate.style,
            "tier": hit.tier,
            "taken": bool(decision and decision.allowed),
            "sector": sector,
            "hold_days": hit.candidate.hold_days,
        })
        ledger.record("stocks", asset.symbol, hit.candidate.side,
                      hit.conviction_pct / 100.0,
                      plan.stop_distance_pct if plan else 0.0, close,
                      # Scored at the strategy's real holding period. It was
                      # 24 hours, so the live record measured one-day trades
                      # while every historical test measured ten-day ones.
                      # Trading days to calendar hours: x 7/5 x 24.
                      hit.candidate.hold_days * 24 * 7 // 5,
                      payload=liquidity)

        if decision and decision.allowed:
            hits.append(hit)
            state = RiskState(
                equity=state.equity,
                open_risk=state.open_risk + decision.risk_fraction,
                deployed=state.deployed + decision.size,
                open_positions=state.open_positions + 1,
                loss_streak=state.loss_streak,
                day_pnl_pct=state.day_pnl_pct,
                peak_equity=state.peak_equity)
            sector_count[sector] = sector_count.get(sector, 0) + 1

    # `recorded` counts every signal written down; `signals` counts what risk
    # actually allowed. The gap between them is the risk rules doing their job
    # and must stay visible.
    surprises = record_confirmed_surprises(
        ledger, sorted(surprise_candidates, key=lambda c: -c[2]))
    if surprises:
        print(f"confirmed surprises recorded on paper: {surprises}")
    ledger.log_run("stocks", looked, len(hits), "",
                   recorded=len(hits) + len(refused))
    print(summarise(hits, looked))
    if refused:
        print(f"\n  {len(refused)} signal(s) recorded but NOT taken — the risk "
              "rules refused them. They stay in the record as evidence about "
              "the setup; they were simply not affordable.")
        for line in refused[:8]:
            print(f"    {line}")
        if len(refused) > 8:
            print(f"    ... and {len(refused) - 8} more")
    if skipped:
        print(f"\n  {skipped} name(s) skipped for want of price history.")
    proven = [h for h in hits if h.tier == PROVEN]
    if proven:
        default_messenger().send(
            "Worth acting on:\n  " + "\n  ".join(
                f"{h.symbol}: {h.candidate.plain}" for h in proven))


def _seed_risk_state(ledger, settings=SETTINGS):
    """The account as it actually stands, for the risk rules to judge.

    Equity and its high-water mark come from replaying the stocks model's own
    closed trades, so drawdown is real. The losing streak and today's P&L come
    from the same record. Anything that cannot be read falls back to a fresh
    account — the one direction that cannot switch a breaker off by mistake is
    starting clean, and the failure is recorded so it is not silent.
    """
    from datetime import datetime, timezone

    from .paper import replay
    from .risk import RiskState

    try:
        book = replay(settings.shadow_db, models={"stocks"})
        equity = float(book.equity)
        peak = equity
        running = float(book.starting_cash)
        for t in book.trades:
            running += t.pnl
            peak = max(peak, running)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_pnl = sum(t.pnl for t in book.trades
                      if str(t.opened_at)[:10] == today)
        from .risk import RISK_PER_TRADE
        open_n, _sectors = _open_book(ledger)
        return RiskState(
            equity=equity,
            peak_equity=max(peak, equity),
            day_pnl_pct=(day_pnl / equity) if equity else 0.0,
            loss_streak=ledger.current_loss_streak("stocks"),
            open_positions=open_n,
            open_risk=open_n * RISK_PER_TRADE,
        )
    except Exception as exc:  # noqa: BLE001  # handled: recorded, and a fresh book is used
        record_skip("stocks", "risk-state", exc)
        return RiskState(equity=100_000.0)


def _williams(bars) -> float | None:
    """Williams %R over the last 14 sessions, or None if it cannot be formed."""
    if len(bars) < 14 or "high" not in bars or "low" not in bars:
        return None
    high = float(bars["high"].tail(14).max())
    low = float(bars["low"].tail(14).min())
    if high <= low:
        return None
    return (high - float(bars["close"].iloc[-1])) / (high - low) * -100.0


def _atr_last(bars) -> float | None:
    """Average true range, or None when the columns are not present."""
    if len(bars) < 14 or "high" not in bars or "low" not in bars:
        return None
    spans = (bars["high"].tail(14) - bars["low"].tail(14))
    return float(spans.mean())


def run_profiles(settings=SETTINGS) -> None:
    """Measure how each board name behaves after a fall.

    This is the replacement purpose for the daily model. Predicting tomorrow's
    direction on every asset every session produced 51.4% against a 52.2%
    base across 141,123 decisions — a question that could not be answered.
    "How does this name behave after a fall?" IS answerable: the rank order
    persisted at Spearman +0.398 across two halves of a decade, and the
    bottom of that order persisted roughly twice as well as the top.

    The output is not a forecast. It is the veto list every other model
    consults before acting, which is worth more than another daily guess.
    """
    from datetime import datetime, timedelta, timezone

    from .personality import profile_from_closes, summarise

    market = YahooProvider()
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    profiles = []
    for asset in board_assets(settings):
        try:
            bars = market.history(asset.symbol, settings.history_start, end)
            closes = [float(x) for x in bars["close"].tolist() if x and x > 0]
        except Exception as exc:  # noqa: BLE001
            record_skip("profiles", asset.symbol, exc)
            continue
        if len(closes) > 60:
            profiles.append(profile_from_closes(asset.symbol, closes))

    print(summarise(profiles))


def run_diagnose(settings=SETTINGS) -> None:
    """Name what is blocking each model, now, instead of in six months.

    Waiting for a verdict tells you a model failed but never why, and by then
    the cause is weeks of data behind you. Every model is stuck on exactly one
    of five things, and each has a different response:

      NO DATA        nothing recorded — the scanner is not running
      NOT RESOLVING  recorded but never scored — the resolver is behind
      TOO EARLY      scoring fine, sample too small to conclude anything
      NO EDGE        enough sample, hit rate at or below its own chance level
      NO ROOM        beating chance, but the cost bar leaves too little to win

    The last one is the one nobody looks for and the one that wastes the most
    time: a model can be genuinely skilful and still never clear a bar that
    the horizon makes unreachable.
    """
    import sqlite3
    from contextlib import closing

    from .export_app import TARGET_CHECKS
    from .shadow import ShadowLedger
    from .stats import wilson_interval

    ledger = ShadowLedger(settings.shadow_db)
    lines = ["What is blocking each model", ""]

    with closing(sqlite3.connect(settings.shadow_db)) as con:
        models = [r[0] for r in con.execute(
            "SELECT DISTINCT model FROM predictions ORDER BY model")]
        known = sorted(set(models) | set(TARGET_CHECKS))

        for model in known:
            recorded = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE model=?",
                (model,)).fetchone()[0]
            resolved, hits = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(hit), 0) FROM predictions "
                "WHERE model=? AND hit IS NOT NULL", (model,)).fetchone()
            movers = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE model=? "
                "AND entry_price>0 AND exit_price>0 "
                "AND ABS(exit_price/entry_price - 1.0) > 0.0015",
                (model,)).fetchone()[0]
            frozen = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE model=? "
                "AND hit IS NOT NULL AND exit_price = entry_price",
                (model,)).fetchone()[0]
            target = TARGET_CHECKS.get(model, 500)

            if not recorded:
                verdict = ("NO DATA — nothing has been recorded. The scanner "
                           "is not running, or it declines on every item.")
                fix = "Check the job runs on the schedule and look at its skips."
            elif resolved == 0:
                verdict = (f"NOT RESOLVING — {recorded:,} recorded, none "
                           "scored. Forecasts are being written but never "
                           "closed out.")
                fix = "Run the resolve job; check prices are reachable."
            elif resolved < target * 0.5:
                pct = resolved / target * 100
                verdict = (f"TOO EARLY — {resolved:,} of {target:,} checks "
                           f"({pct:.0f}%). Nothing can be concluded yet and "
                           "no number here means anything.")
                fix = "Wait. Judge at the target, not before."
            else:
                null = ledger.empirical_null(model)
                rate = hits / resolved
                lower, _ = wilson_interval(hits, resolved, 0.90)
                winnable = movers / resolved if resolved else 0.0

                # Frozen rows used to make this fire constantly: an exit
                # price identical to entry counts as a non-mover, so a
                # resolver bug read as "the market does not move enough".
                # Real daily closes clear the cost bar 94% of the time, so a
                # low reading here now means the DATA is wrong, not the market.
                if frozen > resolved * 0.05:
                    verdict = (f"BAD DATA — {frozen:,} of {resolved:,} rows "
                               "have an exit price identical to the entry, "
                               "which means no new bar was read. Each scores "
                               "an automatic miss and drags the chance level "
                               "down with it.")
                    fix = ("Run `python -m sigbot.runner reset` to unscore "
                           "them, then let them resolve against real bars.")
                elif winnable < 0.5:
                    verdict = (f"NO ROOM — only {winnable * 100:.0f}% of "
                               "windows move more than the cost of trading "
                               f"them, so even a perfect forecast caps at "
                               f"{winnable * 100:.0f}%.")
                    fix = ("Lengthen the horizon. This is not a skill problem "
                           "and more data will not fix it.")
                elif lower <= null:
                    verdict = (f"NO EDGE — {rate * 100:.1f}% against a chance "
                               f"level of {null * 100:.1f}%, worst case "
                               f"{lower * 100:.1f}%. The cautious reading does "
                               "not clear chance.")
                    fix = ("Change the signal or retire it. More of the same "
                           "data will reproduce this.")
                else:
                    verdict = (f"WORKING — {rate * 100:.1f}% against "
                               f"{null * 100:.1f}% chance, worst case "
                               f"{lower * 100:.1f}% still above it.")
                    fix = "Keep running it and let the sample grow."

            lines.append(f"  {model}")
            lines.append(f"    {verdict}")
            lines.append(f"    -> {fix}")
            lines.append("")

    lines.append("  Read this monthly. A model that moves from TOO EARLY to "
                 "NO EDGE has answered its question and should be changed or "
                 "dropped; one that reaches NO ROOM was never going to work "
                 "at that horizon however good it was.")
    print("\n".join(lines))


def run_horizons(settings=SETTINGS) -> None:
    """How much room each horizon leaves for an edge to exist at all.

    A call only counts when the move also clears the cost of trading, so at a
    short horizon most sessions are unwinnable no matter who forecasts them.
    This measures the ceiling a PERFECT forecaster would hit at each horizon —
    and therefore how much room the model has to show skill.

    It does not say the model is good. It says whether the question it is
    being asked can be answered profitably at all.
    """
    from datetime import datetime, timedelta, timezone

    import statistics

    cost = 0.0015

    # REAL market history, not the ledger's entry-price snapshots.
    #
    # The first version of this read `entry_price` from predictions and
    # treated consecutive rows as consecutive sessions. They are not: several
    # land within the same day, so "one bar" was often minutes. It reported a
    # median 1-day move of 0.06% and claimed only 43% of windows could clear
    # the cost bar. Real daily closes for the same names say 1.57% and 94%.
    #
    # That error did not just misstate a number — it produced the diagnosis
    # "the horizon leaves no room", which pointed at markets when the real
    # cause was a resolver reading the same quote twice. A measurement taken
    # from the thing being measured will confirm whatever is wrong with it.
    market = YahooProvider()
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=730)).strftime("%Y-%m-%d")

    series: dict[str, list[float]] = {}
    for asset in [a for a in board_assets(settings) if a.kind != "crypto"][:40]:
        try:
            bars = market.history(asset.symbol, start, end)
            closes = [float(x) for x in bars["close"].tolist() if x and x > 0]
        except Exception as exc:  # noqa: BLE001
            record_skip("horizons", asset.symbol, exc)
            continue
        if len(closes) > 30:
            series[asset.symbol] = closes

    lines = ["Horizon room — what a perfect forecaster could score", ""]
    lines.append(f"  {'bars':>5} {'winnable':>10} {'median move':>13} "
                 f"{'chance':>9} {'max edge':>10}")
    for horizon in (1, 2, 3, 5, 10):
        moves = []
        for prices in series.values():
            for i in range(len(prices) - horizon):
                a, b = prices[i], prices[i + horizon]
                if a > 0 and b > 0:
                    moves.append(abs(b / a - 1.0))
        if not moves:
            continue
        winnable = sum(1 for m in moves if m > cost) / len(moves)
        lines.append(f"  {horizon:>5} {winnable * 100:>9.0f}% "
                     f"{statistics.median(moves) * 100:>12.2f}% "
                     f"{winnable * 50:>8.0f}% {winnable * 50:>9.0f}pp")

    lines.append("")
    lines.append("  'winnable' is the share of windows where the move beats "
                 "the cost bar. A move under it is a miss however well it was "
                 "called, so that share is the hit-rate ceiling. Chance is "
                 "half of it, and the gap between them is all the room an "
                 "edge has to appear in.")
    lines.append("  A longer horizon does not create an edge. It gives an "
                 "existing one somewhere to show up.")
    print("\n".join(lines))


def run_paper() -> None:
    """The sixth model: replay the ledger as a portfolio and report the money.

    Reads only prices already stored by the other five. No broker, no key, no
    network — so this job cannot place an order even by accident, and it
    produces the same answer on any machine given the same ledger.
    """
    from . import paper

    # Only models that earned the right to be traded. Replaying every
    # recorded forecast measured cost drag on noise, not the worth of the
    # signals — the single biggest misreading this system has produced.
    gated = paper.gated_models(SETTINGS.shadow_db)
    book = paper.replay(SETTINGS.shadow_db, models=gated or {"__none__"})
    benchmark = paper.replay(SETTINGS.shadow_db)
    print(paper.summary(book, benchmark=benchmark, gated=gated))
    paper.write_state(book, benchmark=benchmark, gated=gated)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "daily"
    jobs: dict[str, Callable[[], None]] = {
        # Daily outlook is now Stocks. The old job name is kept as an alias so
        # a workflow that still says "daily" runs the scan instead of
        # silently running a retired model.
        "daily": lambda: run_stocks(),
        "daily-legacy": run_daily,
        "news": run_news,
        "contagion": run_contagion,
        "opportunities": run_opportunities,
        "resolve": run_resolve,
        "cycle": run_cycle,
        "report": run_report,
        "publish": run_publish,
        "day_summary": run_day_summary,
        "crypto15m": run_crypto15m,
        "paper": run_paper,
        "backtest": run_backtest,
        "horizons": run_horizons,
        "diagnose": run_diagnose,
        "setups": lambda: run_stocks(),
        "profiles": run_profiles,
        "stocks": run_stocks,
        "priority": run_priority,
        "priority-run": lambda: run_priority(execute=True),
        "events": run_events,
        "review": run_review,
        "promotion": run_promotion,
        "research": run_research,
        "outcomes": run_outcomes,
        "reset": run_reset,
        "reset-all": lambda: run_reset(full=True),
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
