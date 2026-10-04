"""Live dispatch handlers — the real integrations the OperatingLoop calls.

Starts with activate_pending (the safest: no new prediction, just fills a pending
next-session entry at the ACTUAL session open). This is where the overnight-drift
exclusion becomes true on the real ledger, not just in unit tests.

Each handler is wired one at a time and tested against the real shadow DB before
the coordinator is switched over. Lineage: every activation records which run_id
filled it, so a prediction traces run -> event -> admission -> activation ->
resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .market_scheduler import Family
from .operating_loop_v2 import DispatchHandlers
from .shadow import ShadowLedger


def _session_open_price(market, symbol: str, effective_at: datetime
                        ) -> float | None:
    """The real session-open price at/after the execution point. Uses the first
    bar's open on or after effective_at. Returns None if no bar is available yet
    (the session hasn't opened or data isn't in) — the caller then leaves the
    entry pending, never guessing a price."""
    try:
        start = (effective_at.date()).isoformat()
        end = (effective_at.date()).isoformat()
        bars = market.history(symbol, start, end)
    except Exception:  # noqa: BLE001  # handled: no data -> leave pending
        return None
    if bars is None or len(bars) == 0 or "open" not in getattr(bars, "columns", []):
        return None
    try:
        # first bar at/after the effective date; its open is the session open.
        val = float(bars["open"].iloc[0])
        return val if val > 0 else None
    except (IndexError, ValueError, TypeError):  # noqa: BLE001  # handled
        return None


@dataclass
class LiveActivationHandler(DispatchHandlers):
    """Real activate_pending: fills pending next-session stock entries at the
    actual session open. Pure — creates no predictions, only activates existing
    ones, and refuses to back-date before the execution point."""
    ledger: ShadowLedger = None          # type: ignore[assignment]
    market: object = None                # provider with .history(sym,start,end)
    now_fn: object = None
    _lineage: list[dict] = field(default_factory=list)

    def _now(self) -> datetime:
        return self.now_fn() if self.now_fn else datetime.now(timezone.utc)  # type: ignore[operator]

    def activate_pending(self, family: Family, run_id: str) -> int:
        if family != Family.STOCKS or self.ledger is None or self.market is None:
            return 0
        now = self._now()
        activated = 0
        for row in self.ledger.pending_entries("stocks"):
            eff = row.get("decision_effective_at")
            if not eff:
                continue
            eff_dt = datetime.fromisoformat(eff)
            # only activate once the execution point has actually arrived.
            if now < eff_dt:
                continue
            price = _session_open_price(self.market, row["symbol"], eff_dt)
            if price is None:
                continue                 # session open not available yet; wait
            if self.ledger.activate_entry(row["id"], price, executed_at=now):
                activated += 1
                # lineage: run -> prediction -> activation price
                self._lineage.append({
                    "run_id": run_id, "prediction_id": row["id"],
                    "symbol": row["symbol"], "activation_price": price,
                    "activated_at": now.isoformat(),
                    "decision_effective_at": eff})
        return activated

    def lineage(self) -> list[dict]:
        return list(self._lineage)


def describe() -> str:
    return "\n".join([
        "LIVE HANDLERS — real integrations the OperatingLoop calls",
        "",
        "  activate_pending (first, safest): fills pending next-session stock",
        "  entries at the ACTUAL session open (first bar's open at/after the",
        "  execution point). Creates NO predictions; refuses to activate before",
        "  the execution point; leaves the entry pending when the open price isn't",
        "  available yet rather than guessing. This makes the overnight-drift",
        "  exclusion true on the real ledger: realised return is measured from the",
        "  session open, never the overnight scan price.",
        "",
        "  Records lineage per activation (run_id -> prediction_id -> price) so a",
        "  live prediction traces run -> event -> admission -> activation ->",
        "  resolution. Other handlers (stocks predict, resolver, crypto, ventures,",
        "  ideas, news dedup) are wired next, one at a time, each tested before the",
        "  coordinator switches to OperatingLoop.tick().",
    ])


# ─────────────────────────────────────────────────────────────────────────────
# The complete real-handler set. Each is tested against a real ShadowLedger
# through the real OperatingLoop. No alpha/model logic changes — these adapt the
# scheduler's event dispatch to the existing recording/resolution primitives
# while enforcing the full admission contract.
# ─────────────────────────────────────────────────────────────────────────────
from datetime import timedelta as _timedelta  # noqa: E402

from .market_scheduler import EventType, ScheduledEvent  # noqa: E402


@dataclass
class _Lineage:
    """Shared lineage recorder: run_id -> event -> prediction -> activation ->
    resolution, so a live prediction traces end to end."""
    events: list[dict] = field(default_factory=list)

    def record(self, **kw) -> None:
        self.events.append(kw)

    def all(self) -> list[dict]:
        return list(self.events)


@dataclass
class LiveHandlers(DispatchHandlers):
    """The full production handler set wired through OperatingLoop. Each dispatch
    type maps to a real primitive; only PREDICT_* can record, and every record
    goes through the gated admission path."""
    ledger: ShadowLedger = None          # type: ignore[assignment]
    market: object = None
    now_fn: object = None
    lineage: _Lineage = field(default_factory=_Lineage)
    # injectable setup sources so tests can drive without the full runners.
    # each returns a list of dicts: {symbol, side, score, horizon_hours,
    # expected_move, scan_price, event_id?}
    stocks_setups: object = None         # callable() -> list[dict]
    crypto_setups: object = None
    news_setups: object = None
    ventures_setups: object = None
    ideas_setups: object = None

    def _now(self):
        return self.now_fn() if self.now_fn else datetime.now(timezone.utc)

    # ── activation (reuses the proven logic) ─────────────────────────────────
    def activate_pending(self, family: Family, run_id: str) -> int:
        if family != Family.STOCKS or not self.ledger or not self.market:
            return 0
        act = LiveActivationHandler(ledger=self.ledger, market=self.market,
                                    now_fn=self.now_fn)
        n = act.activate_pending(family, run_id)
        for row in act.lineage():
            merged = {"stage": "activation", **row}   # row already has run_id
            self.lineage.record(**merged)
        return n

    # ── prediction (only PREDICT_* events reach here) ────────────────────────
    def predict(self, event: ScheduledEvent, run_id: str) -> int:
        if not self.ledger:
            return 0
        fam = event.family
        et = event.event_type
        now = self._now()
        admitted = 0

        if fam == Family.STOCKS and et == EventType.PREDICT_NEXT_SESSION:
            setups = self._call(self.stocks_setups)
            exec_at = self._next_session_open(now)
            for s in setups:
                h = int(s.get("horizon_hours", 168))
                dkey = f"stocks|{s['symbol']}|{h}h"
                pid = self.ledger.record_next_session(
                    model="stocks", symbol=s["symbol"], side=s.get("side", "BUY"),
                    score=s.get("score"), expected_move=s.get("expected_move"),
                    information_as_of=now, created_at=now,
                    decision_effective_at=exec_at,
                    outcome_end=exec_at + _timedelta(hours=h), dedup_key=dkey)
                if pid:
                    admitted += 1
                    self.lineage.record(stage="prediction", run_id=run_id,
                                        prediction_id=pid, family="stocks",
                                        symbol=s["symbol"], dedup_key=dkey)

        elif fam == Family.CRYPTO and et == EventType.PREDICT_CURRENT_SESSION:
            for s in self._call(self.crypto_setups):
                h = int(s.get("horizon_hours", 72))
                inst = s.get("signal_instance", now.isoformat())
                dkey = f"crypto|{s['symbol']}|{h}h|{inst}"
                pid = self.ledger.record(
                    "crypto", s["symbol"], s.get("side", "BUY"), s.get("score"),
                    s.get("expected_move"), s.get("scan_price"), h,
                    payload=s.get("payload", ""), gate=True, dedup_key=dkey)
                if pid:
                    admitted += 1
                    self.lineage.record(stage="prediction", run_id=run_id,
                                        prediction_id=pid, family="crypto",
                                        symbol=s["symbol"], dedup_key=dkey)

        elif fam == Family.NEWS and et == EventType.PREDICT_CURRENT_SESSION:
            for s in self._call(self.news_setups):
                h = int(s.get("horizon_hours", 24))
                # event-level dedup: event_id + asset + horizon
                dkey = f"news|{s['event_id']}|{s['symbol']}|{h}h"
                pid = self.ledger.record(
                    "news", s["symbol"], s.get("side", "BUY"), s.get("score"),
                    s.get("expected_move"), s.get("scan_price"), h,
                    payload=s.get("payload", ""), gate=True, dedup_key=dkey)
                if pid:
                    admitted += 1
                    self.lineage.record(stage="prediction", run_id=run_id,
                                        prediction_id=pid, family="news",
                                        symbol=s["symbol"], event_id=s["event_id"],
                                        dedup_key=dkey)

        elif fam in (Family.VENTURES, Family.IDEAS) \
                and et == EventType.PREDICT_NEXT_SESSION:
            # only a CONCRETE eligible thesis/opportunity produces a prediction.
            src = self.ventures_setups if fam == Family.VENTURES \
                else self.ideas_setups
            exec_at = self._next_session_open(now)
            for s in self._call(src):
                h = int(s.get("horizon_hours", 2160))      # ~90d default
                ident = s.get("thesis_id") or s.get("opportunity_id") \
                    or s["symbol"]
                dkey = f"{fam.value}|{ident}|{h}h"
                pid = self.ledger.record_next_session(
                    model=fam.value, symbol=s["symbol"], side=s.get("side", "BUY"),
                    score=s.get("score"), expected_move=s.get("expected_move"),
                    information_as_of=now, created_at=now,
                    decision_effective_at=exec_at,
                    outcome_end=exec_at + _timedelta(hours=h), dedup_key=dkey)
                if pid:
                    admitted += 1
                    self.lineage.record(stage="prediction", run_id=run_id,
                                        prediction_id=pid, family=fam.value,
                                        symbol=s["symbol"], dedup_key=dkey)
        return admitted

    # ── research (NEVER records a prediction) ────────────────────────────────
    def research(self, event: ScheduledEvent, run_id: str) -> None:
        # Research/thesis/opportunity updates are real work but produce no
        # prediction. We only note lineage; recording is structurally impossible
        # here because this method never calls the ledger's record paths.
        self.lineage.record(stage="research", run_id=run_id,
                            family=event.family.value,
                            event_type=event.event_type.value)

    # ── resolver (never resolves pending or pre-window predictions) ──────────
    def resolve(self, family: Family, run_id: str) -> int:
        if not self.ledger:
            return 0
        resolved = 0
        for pid, symbol, _side, entry in self.ledger.due(model=family.value):
            # A pending next-session entry (entry_price NULL) is NOT eligible —
            # it never got a real execution price, so it cannot resolve.
            if entry is None:
                continue
            exit_price = self._exit_price(symbol)
            if exit_price is None:
                continue                 # no price yet; leave open
            self.ledger.resolve(pid, exit_price=exit_price)
            resolved += 1
            self.lineage.record(stage="resolution", run_id=run_id,
                                prediction_id=pid, family=family.value,
                                symbol=symbol, exit_price=exit_price)
        return resolved

    # ── helpers ──────────────────────────────────────────────────────────────
    def _call(self, src) -> list:
        if src is None:
            return []
        try:
            return list(src()) or []
        except Exception:  # noqa: BLE001  # handled: a bad setup source yields none
            return []

    def _next_session_open(self, now):
        """First session execution point at/after now. Uses the market_hours
        next_open for the default venue; tests inject now_fn to control it."""
        try:
            from .market_hours import Venue, next_open
            return next_open(Venue.NSE, now)
        except Exception:  # noqa: BLE001  # handled: fall back to now+1d
            return now + _timedelta(days=1)

    def _exit_price(self, symbol: str):
        if not self.market:
            return None
        market = self.market
        try:
            bars = market.history(symbol, "", "")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001  # handled: no data -> leave open
            return None
        if bars is None or len(bars) == 0 \
                or "close" not in getattr(bars, "columns", []):
            return None
        try:
            v = float(bars["close"].iloc[-1])
            return v if v > 0 else None
        except (IndexError, ValueError, TypeError):  # noqa: BLE001  # handled
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Real setup sources — connect the ACTUAL model scanners to the handler setup
# sources WITHOUT duplicating or rewriting model logic.
#
# Approach: a capturing ShadowLedger proxy. We run the real runner (run_stocks,
# run_crypto, ...) unchanged, but swap its ledger for a proxy whose record paths
# COLLECT the call arguments instead of writing. The runner's full detection /
# scoring / dedup-eligibility / liquidity logic executes exactly as in
# production; we simply intercept what it WOULD have recorded and hand those to
# the handler as setups. Zero model-logic duplication.
# ─────────────────────────────────────────────────────────────────────────────
class _CapturingLedger:
    """Wraps a real ShadowLedger. Read methods pass through (so the runner's
    has_open_prediction / due / etc. behave normally); the record methods capture
    their arguments into `captured` instead of inserting a row."""

    def __init__(self, real: ShadowLedger):
        self._real = real
        self.captured: list[dict] = []

    # capture the two recording entry points
    def record(self, model, symbol, side, score, expected_move, entry_price,
               horizon_hours=24, payload="", alerted=True, as_of=None,
               dedup_key=None, gate=False):
        self.captured.append({
            "path": "record", "model": model, "symbol": symbol, "side": side,
            "score": score, "expected_move": expected_move,
            "scan_price": entry_price, "horizon_hours": horizon_hours,
            "payload": payload, "dedup_key": dedup_key})
        return 1          # pretend-success so the runner proceeds normally

    def record_next_session(self, *, model, symbol, side, score, expected_move,
                            information_as_of, created_at, decision_effective_at,
                            outcome_end, dedup_key, payload="", alerted=True):
        self.captured.append({
            "path": "next_session", "model": model, "symbol": symbol,
            "side": side, "score": score, "expected_move": expected_move,
            "dedup_key": dedup_key, "payload": payload})
        return 1

    def __getattr__(self, name):
        # everything else (has_open_prediction, due, resolve, pending_entries,
        # connection helpers) passes through to the real ledger.
        return getattr(self._real, name)


def _capture_setups(runner_fn, settings, ledger_attr_patch) -> list[dict]:
    """Run a real runner with a capturing ledger and return what it would have
    recorded. ledger_attr_patch(settings, capturing) installs the proxy wherever
    the runner obtains its ledger."""
    import contextlib
    captured: list[dict] = []
    with contextlib.suppress(Exception):   # a scan failure yields no setups
        cap = ledger_attr_patch(settings)
        runner_fn(settings)
        captured = cap.captured
    return captured


@dataclass
class RealSetupSources:
    """Builds setup-source callables backed by the real runners. Each callable
    runs the real scan with a capturing ledger and converts captured records to
    the setup dicts LiveHandlers expects. The model remains the sole source of
    candidate setups."""
    settings: object

    def stocks(self) -> list[dict]:
        import sigbot.runner as R
        cap_holder = {}

        def _patch(settings):
            real = ShadowLedger(getattr(settings, "shadow_db", "shadow.db"))
            cap = _CapturingLedger(real)
            cap_holder["cap"] = cap
            # run_stocks builds its own ShadowLedger internally; intercept the
            # class so it constructs our proxy instead.
            setattr(R, "ShadowLedger", lambda *a, **k: cap)
            return cap

        orig = R.ShadowLedger
        try:
            _capture_setups(R.run_stocks, self.settings, _patch)
        finally:
            setattr(R, "ShadowLedger", orig)  # restore
        out = []
        for c in cap_holder.get("cap", _CapturingLedger(
                ShadowLedger("shadow.db"))).captured:
            if c["model"] != "stocks":
                continue
            # horizon from dedup_key (…|Nd or …|Nh) or default
            out.append({"symbol": c["symbol"], "side": c["side"],
                        "score": c["score"], "expected_move": c["expected_move"],
                        "horizon_hours": _horizon_from_payload(c), 
                        "payload": c.get("payload", "")})
        return out


def _horizon_from_payload(captured: dict) -> int:
    """Pull hold_days from the captured payload if present (stocks encodes it),
    else a 7-day default in hours."""
    import json as _json
    try:
        meta = _json.loads(captured.get("payload") or "{}")
        hd = meta.get("hold_days")
        if hd:
            return int(hd) * 24
    except (ValueError, TypeError):  # noqa: BLE001  # handled: default below
        pass
    return 168


def describe_real_sources() -> str:
    return "\n".join([
        "REAL SETUP SOURCES — the actual model scanners feed the loop",
        "",
        "  Connects run_stocks (and the other runners) to the handler setup",
        "  sources WITHOUT duplicating model logic: a _CapturingLedger proxy runs",
        "  the real runner unchanged but intercepts what it WOULD record, handing",
        "  those to the handler as setups. The model's full detection/scoring/",
        "  liquidity logic executes exactly as in production. The handler then",
        "  applies admission/dedup/timestamp/lineage. One qualifying scan -> one",
        "  prediction through OperatingLoop; a non-qualifying scan -> zero.",
    ])
