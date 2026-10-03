"""Market-aware scheduler — event taxonomy, market clocks, timestamp contract."""
from datetime import datetime, timedelta, timezone

from sigbot.market_scheduler import (
    EventType, Family, MarketPhase, MarketScheduler, MarketState,
    PredictAction, Priority, can_create_prediction,
    priority_for)

# Sunday 02:00 UTC — both equity venues closed, crypto open
CLOSED = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)
# Monday 10:00 UTC — NYSE open (but this is a holiday-free assumption)
# Use a time NSE is open: 09:15-15:30 IST = 03:45-10:00 UTC on a weekday
NSE_OPEN = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)   # Monday ~10:30 IST


# ── event taxonomy: only PREDICT creates predictions ────────────────────────
def test_only_predict_can_create_prediction():
    assert can_create_prediction(EventType.PREDICT_NEXT_SESSION)
    assert can_create_prediction(EventType.PREDICT_CURRENT_SESSION)
    for et in (EventType.SCAN, EventType.RESEARCH, EventType.PREPARE,
               EventType.RESOLVE, EventType.MONITOR, EventType.RECOVER,
               EventType.THESIS_UPDATE, EventType.OPPORTUNITY_UPDATE):
        assert not can_create_prediction(et)


# ── market state observation ────────────────────────────────────────────────
def test_closed_state_has_crypto_open():
    st = MarketState.observe(CLOSED)
    assert st.equities_phase == MarketPhase.CLOSED
    assert st.crypto_open


# ── priority: market-aware ──────────────────────────────────────────────────
def test_stocks_background_when_closed():
    st = MarketState.observe(CLOSED)
    assert priority_for(Family.STOCKS, st) == Priority.BACKGROUND


def test_ventures_high_when_equities_closed():
    st = MarketState.observe(CLOSED)
    assert priority_for(Family.VENTURES, st) == Priority.HIGH
    assert priority_for(Family.IDEAS, st) == Priority.HIGH


def test_crypto_high_when_equities_closed():
    st = MarketState.observe(CLOSED)
    assert priority_for(Family.CRYPTO, st) == Priority.HIGH


def test_news_boosts_on_event_burst():
    st = MarketState.observe(CLOSED)
    assert priority_for(Family.NEWS, st, event_queue=50) == Priority.HIGH
    assert priority_for(Family.NEWS, st, event_queue=0) == Priority.EVENT_DRIVEN


def test_no_family_below_its_minimum():
    """Service-level budget: nothing is starved below its floor."""
    st = MarketState.observe(CLOSED)
    for fam in Family:
        p = priority_for(fam, st)
        assert p is not None


# ── plan_tick: event types by phase ─────────────────────────────────────────
def test_closed_tick_stocks_predicts_next_session():
    """CORRECTED: stocks predicts the NEXT session while the market is closed —
    the prediction is about a future execution window, frozen before the move."""
    sched = MarketScheduler()
    events = sched.plan_tick(CLOSED)
    stocks_events = [e for e in events if e.family == Family.STOCKS]
    # predicts next session, and still resolves/prepares
    assert any(e.event_type == EventType.PREDICT_NEXT_SESSION
               for e in stocks_events)
    assert any(e.event_type == EventType.RESOLVE for e in stocks_events)
    assert any(e.event_type == EventType.PREPARE for e in stocks_events)
    # NEVER a current-session mint when closed
    assert all(e.event_type != EventType.PREDICT_CURRENT_SESSION
               for e in stocks_events)


def test_open_tick_stocks_does_not_mint_new_prediction():
    """When the market is OPEN, stocks only monitors/resolves — no retroactive
    prediction of a move already underway."""
    sched = MarketScheduler()
    # NSE open ~10:30 IST = 05:00 UTC Monday
    nse_open = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)
    events = sched.plan_tick(nse_open)
    stocks = [e for e in events if e.family == Family.STOCKS]
    assert all(not can_create_prediction(e.event_type) for e in stocks)
    assert any(e.event_type == EventType.MONITOR for e in stocks)


def test_news_no_event_no_predict():
    sched = MarketScheduler()
    events = sched.plan_tick(CLOSED, news_queue=0)
    news_events = [e for e in events if e.family == Family.NEWS]
    assert all(not can_create_prediction(e.event_type) for e in news_events)


def test_news_with_event_gets_predict():
    sched = MarketScheduler()
    events = sched.plan_tick(CLOSED, news_queue=5)
    news_events = [e for e in events if e.family == Family.NEWS]
    assert any(can_create_prediction(e.event_type) for e in news_events)


def test_crypto_predicts_continuously():
    sched = MarketScheduler()
    events = sched.plan_tick(CLOSED)
    crypto_events = [e for e in events if e.family == Family.CRYPTO]
    assert any(can_create_prediction(e.event_type) for e in crypto_events)


def test_ventures_backlog_triggers_predict():
    sched = MarketScheduler()
    no_backlog = sched.plan_tick(CLOSED, ventures_backlog=0)
    with_backlog = sched.plan_tick(CLOSED, ventures_backlog=30)
    v_no = [e for e in no_backlog if e.family == Family.VENTURES
            and can_create_prediction(e.event_type)]
    v_yes = [e for e in with_backlog if e.family == Family.VENTURES
             and can_create_prediction(e.event_type)]
    assert len(v_no) == 0 and len(v_yes) >= 1


def test_ventures_research_is_not_prediction():
    """Research (thesis_update) is separate from prediction — cleaner audit."""
    sched = MarketScheduler()
    events = sched.plan_tick(CLOSED, ventures_backlog=0)
    v = [e for e in events if e.family == Family.VENTURES]
    assert any(e.event_type == EventType.THESIS_UPDATE for e in v)
    assert all(not can_create_prediction(e.event_type) for e in v)  # no backlog


def test_every_family_appears_every_tick():
    """No family silently disappears — all five are always present."""
    sched = MarketScheduler()
    events = sched.plan_tick(CLOSED)
    families = {e.family for e in events}
    assert families == set(Family)


# ── the corrected timestamp contract ────────────────────────────────────────
def _pa(**kw):
    base = datetime(2026, 10, 5, 3, 15, tzinfo=timezone.utc)
    nse_open = datetime(2026, 10, 5, 3, 45, tzinfo=timezone.utc)
    d = dict(family=Family.STOCKS, symbol="X", information_as_of=base,
             prediction_created_at=base, decision_effective_at=nse_open,
             outcome_start=nse_open, outcome_end=nse_open + timedelta(days=7),
             horizon="7d")
    d.update(kw)
    return PredictAction(**d)


def test_overnight_call_measured_from_open_is_valid():
    assert _pa().timestamps_valid()


def test_window_from_scan_time_is_invalid():
    """The subtle bug: 'before the move' but measuring from scan not execution."""
    base = datetime(2026, 10, 5, 3, 15, tzinfo=timezone.utc)
    pa = _pa(outcome_start=base)        # window starts at scan, not execution
    assert not pa.timestamps_valid()


def test_information_after_window_invalid():
    future = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
    pa = _pa(information_as_of=future)   # info newer than the call
    assert not pa.timestamps_valid()


def test_news_event_key_distinguishes_events():
    n1 = _pa(family=Family.NEWS, event_id="EV-1", horizon="1d")
    n2 = _pa(family=Family.NEWS, event_id="EV-2", horizon="1d")
    assert n1.dedup_key() != n2.dedup_key()
    assert "EV-1" in n1.dedup_key()


def test_stocks_key_is_symbol_horizon():
    assert _pa(symbol="DEVYANI.NS").dedup_key() == "stocks|DEVYANI.NS|7d"


# ── allocation surface for the website/API ──────────────────────────────────
def test_allocation_comes_from_scheduler():
    sched = MarketScheduler()
    alloc = sched.current_allocation(CLOSED, ventures_backlog=30)
    assert alloc["equities"] == "closed"
    assert alloc["crypto"] == "open"
    assert alloc["ventures"] == "high"
    assert alloc["stocks"] == "background"
