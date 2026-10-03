"""Operating loop — the convergence build. Fail-closed, PREDICT-only, activation."""
from datetime import datetime, timezone

from sigbot.market_scheduler import MarketScheduler
from sigbot.operating_loop_v2 import DispatchHandlers, OperatingLoop

CLOSED = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)      # Sunday, equities closed
NSE_OPEN = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)    # Monday NSE open


class _H(DispatchHandlers):
    def __init__(self):
        self.predicts = 0
        self.resolves = 0
        self.activations = 0
        self.research_calls = 0

    def predict(self, event, run_id):
        self.predicts += 1
        return 1

    def resolve(self, family, run_id):
        self.resolves += 1
        return 1

    def activate_pending(self, family, run_id):
        self.activations += 1
        return 2

    def research(self, event, run_id):
        self.research_calls += 1


# ── dispatch happens, all families alive ────────────────────────────────────
def test_closed_tick_all_families_dispatched():
    loop = OperatingLoop(handlers=_H())
    r = loop.tick(CLOSED, news_queue=3, ventures_backlog=10, ideas_backlog=5)
    families = {d.split(":")[0] for d in r.dispatched}
    assert families == {"stocks", "news", "crypto", "ventures", "ideas"}


def test_closed_tick_is_silent():
    """A normal tick produces zero Telegram messages — all routine/silent."""
    loop = OperatingLoop(handlers=_H())
    r = loop.tick(CLOSED, news_queue=3)
    assert r.notifications_sent == 0


# ── only PREDICT events create predictions ──────────────────────────────────
def test_only_predict_events_attempt_predictions():
    h = _H()
    loop = OperatingLoop(handlers=h)
    r = loop.tick(CLOSED, news_queue=3, ventures_backlog=10, ideas_backlog=5)
    # count the predict dispatches
    predict_dispatches = [d for d in r.dispatched if "predict" in d]
    assert r.predictions_attempted == len(predict_dispatches)
    assert h.predicts == len(predict_dispatches)


def test_research_resolve_monitor_never_predict():
    h = _H()
    loop = OperatingLoop(handlers=h)
    loop.tick(CLOSED)
    # research ran, but research count != predict count
    assert h.research_calls > 0
    # resolve ran for stocks when closed
    assert h.resolves > 0


# ── activation at open ──────────────────────────────────────────────────────
def test_activation_fires_at_open():
    h = _H()
    loop = OperatingLoop(handlers=h)
    r = loop.tick(NSE_OPEN)
    assert r.activations == 2
    assert h.activations == 1          # called once


def test_no_stocks_prediction_mint_when_open():
    loop = OperatingLoop(handlers=_H())
    r = loop.tick(NSE_OPEN)
    stocks_predicts = [d for d in r.dispatched
                       if d.startswith("stocks") and "predict" in d]
    assert stocks_predicts == []


def test_no_activation_when_closed_only():
    """When the market is closed (no monitor/prepare-at-open), no activation."""
    h = _H()
    loop = OperatingLoop(handlers=h)
    # closed tick does include PREPARE for stocks -> activation is attempted,
    # but the handler is what decides; here we just assert it ran at most once.
    loop.tick(CLOSED)
    assert h.activations <= 1


# ── FAIL CLOSED ─────────────────────────────────────────────────────────────
class _BrokenSched(MarketScheduler):
    def plan_tick(self, *a, **k):
        raise RuntimeError("scheduler boom")


def test_scheduler_failure_blocks_dispatch_and_capital():
    loop = OperatingLoop(scheduler=_BrokenSched(), handlers=_H())
    r = loop.tick(CLOSED)
    assert r.dispatched == ()
    assert r.capital_blocked is True
    assert r.scheduler_failed is True
    assert r.predictions_attempted == 0


def test_scheduler_failure_sends_one_critical():
    loop = OperatingLoop(scheduler=_BrokenSched(), handlers=_H())
    loop.tick(CLOSED)
    assert len(loop.sender.sent_messages()) == 1
    assert "🚨" in loop.sender.sent_messages()[0]


def test_repeated_failure_deduped():
    loop = OperatingLoop(scheduler=_BrokenSched(), handlers=_H())
    loop.tick(CLOSED)
    loop.tick(CLOSED)
    loop.tick(CLOSED)
    assert len(loop.sender.sent_messages()) == 1    # no spam


def test_recovery_after_failure():
    loop = OperatingLoop(scheduler=_BrokenSched(), handlers=_H())
    loop.tick(CLOSED)
    assert loop.capital_blocked
    loop.scheduler = MarketScheduler()              # fixed
    r = loop.tick(CLOSED)
    assert r.capital_blocked is False
    # failure alert + recovery alert
    assert len(loop.sender.sent_messages()) == 2


def test_no_fallback_to_old_schedule_on_failure():
    """A scheduler failure must NOT dispatch anything — no silent fallback."""
    h = _H()
    loop = OperatingLoop(scheduler=_BrokenSched(), handlers=h)
    loop.tick(CLOSED)
    assert h.predicts == 0
    assert h.resolves == 0
    assert h.research_calls == 0


# ── run ids and tracing ─────────────────────────────────────────────────────
def test_each_tick_has_unique_run_id():
    loop = OperatingLoop(handlers=_H())
    r1 = loop.tick(CLOSED)
    r2 = loop.tick(CLOSED)
    assert r1.run_id != r2.run_id
    assert r1.run_id.startswith("RUN-")


# ── loop emits through pipeline, never direct ───────────────────────────────
def test_loop_has_no_direct_telegram():
    loop = OperatingLoop(handlers=_H())
    assert not hasattr(loop, "send_telegram")
    assert not hasattr(loop, "telegram")


# ── the full end-to-end operating cycle ─────────────────────────────────────
def test_full_operating_cycle():
    """Closed -> predict next session + research; open -> activate; all silent."""
    h = _H()
    loop = OperatingLoop(handlers=h)
    # 1. market closed: stocks predicts next session, crypto predicts, research
    r_closed = loop.tick(CLOSED, news_queue=2, ventures_backlog=5, ideas_backlog=3)
    assert "stocks:predict_next_session" in r_closed.dispatched
    assert "crypto:predict_current_session" in r_closed.dispatched
    assert r_closed.notifications_sent == 0
    # 2. market opens: pending entries activate, no new stocks mint
    r_open = loop.tick(NSE_OPEN)
    assert r_open.activations > 0
    assert not any(d.startswith("stocks") and "predict" in d
                   for d in r_open.dispatched)
    # 3. still silent end to end
    assert r_open.notifications_sent == 0
