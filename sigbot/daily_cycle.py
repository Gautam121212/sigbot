"""The daily cycle — when predictions are made, trades placed, and pages reset.

THE CLOCK, IN PLAIN TERMS
-------------------------
Anchored to the primary equity market (NSE, India). One "trading day" runs:

  * RESET (a fixed time each day)     — both the Predictions and Paper pages
                                        go blank. Nothing shown.
  * PREDICT (reset -> next open)      — every model makes its forecasts for the
                                        coming session, RISKY ones included, and
                                        they are stored as "the fixed predictions
                                        for tomorrow", dated, with a pass/fail
                                        checker per model.
  * TRADE (open -> close)             — paper trading places and holds trades.
  * CLOSED (close -> reset)           — paper trading is off; the day's result
                                        is frozen and moves into the record.

The reset time is set to one hour after the NSE close (16:30 IST), so the full
session has scored before the day rolls. This is the single knob; everything
else derives from the market calendar in market_hours.py.

WHY ANCHOR TO NSE
-----------------
The stocks model trades Indian equities; that is the market whose open/close
defines "a trading day" for the account. Crypto never closes, so its forecasts
are made each cycle alongside the equity ones and simply hold 24h. The page
does not pretend crypto has a bell.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from .market_hours import Venue, is_open, next_open

ANCHOR = Venue.NSE
ANCHOR_TZ = ZoneInfo("Asia/Kolkata")
RESET_LOCAL = time(16, 30)      # 16:30 IST — one hour after NSE close


# How long before the market opens each horizon's predictions are made and then
# LOCKED (no changes after this) until they resolve into results/trades. Two
# horizons only — no intra-day. Long-term is forecast further out (needs more
# lead and holds longer); short-term is forecast closer to the session.
#   long-term  — predictions made 12h before open, then locked; hold 30+ days.
#   short-term — predictions made 6h before open, then locked; hold up to 30 days.
PREDICTION_LEAD_HOURS = {"long-term": 12, "short-term": 6}

# Once made, predictions are LOCKED this long before open — after the lock they
# cannot change; they can only resolve into a result or a trade. The lock is the
# lead time itself: a prediction made 6h before open is fixed from that moment.
LOCK_BEFORE_OPEN_HOURS = {"long-term": 12, "short-term": 6}


class Phase(str, Enum):
    RESET = "reset"          # just reset; pages blank until predictions run
    PREDICT = "predict"      # predictions being made for the next session
    TRADE = "trade"          # market open; paper trading places trades
    CLOSED = "closed"        # market shut; result frozen, waiting for reset


@dataclass(frozen=True)
class CycleState:
    phase: Phase
    trading_day: str            # the date this cycle's predictions are FOR
    reset_at: datetime          # next reset (UTC)
    next_open: datetime         # next market open (UTC)
    predictions_locked: bool    # True once the market opens — no new forecasts


def _now(when: datetime | None) -> datetime:
    return (when or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _reset_today(local_dt: datetime) -> datetime:
    """The reset moment on local_dt's calendar day, in UTC."""
    r = local_dt.replace(hour=RESET_LOCAL.hour, minute=RESET_LOCAL.minute,
                         second=0, microsecond=0)
    return r.astimezone(timezone.utc)


def cycle_state(when: datetime | None = None) -> CycleState:
    """Where we are in the daily cycle right now."""
    now = _now(when)
    local = now.astimezone(ANCHOR_TZ)
    reset_today = _reset_today(local)

    # The next reset: today's if it's still ahead, else tomorrow's.
    if now < reset_today:
        reset_at = reset_today
    else:
        reset_at = _reset_today(local + timedelta(days=1))

    open_utc = next_open(ANCHOR, now)
    market_open = is_open(ANCHOR, now)

    # The trading day these predictions are FOR: the date of the next open.
    trading_day = open_utc.astimezone(ANCHOR_TZ).strftime("%Y-%m-%d")

    if market_open:
        phase = Phase.TRADE
        locked = True
    elif now >= reset_today and now < open_utc and local.time() >= RESET_LOCAL:
        # After today's reset, before the next open: predictions window.
        phase = Phase.PREDICT
        locked = False
    elif open_utc <= reset_at and now < open_utc:
        # Between a prior close and the next open, still before reset boundary.
        phase = Phase.PREDICT
        locked = False
    else:
        phase = Phase.CLOSED
        locked = True

    # Right at/after reset but predictions not yet run reads as RESET.
    secs_since_reset = (now - reset_today).total_seconds()
    if 0 <= secs_since_reset < 120 and not market_open:
        phase = Phase.RESET

    return CycleState(phase=phase, trading_day=trading_day, reset_at=reset_at,
                      next_open=open_utc, predictions_locked=locked)


# Which horizon each model runs on — decided by its EDGE'S real mechanics, not
# a guess. Long-term = fundamental/slow (holds weeks to a quarter), locked 12h
# before open since timing precision doesn't matter and an early lock leaves time
# to place. Short-term = event/setup-driven (holds days), locked 6h before open
# so the call is fresh. No intra-day — no model's real edge is intra-day.
#   stocks   -> long-term  (sustained-inflection is quarterly; capitulation 5-20d)
#   ventures -> long-term  (venture-inflection holds ~90 days — the slowest edge)
#   news     -> short-term (earnings drift is a 5-10 day move from the open)
#   ideas    -> short-term (catalyst move over ~10 days — enter while fresh)
#   crypto   -> short-term (coiled-spring releases within ~3 days — the fastest)
MODEL_HORIZON = {
    "stocks": "long-term", "ventures": "long-term",
    "news": "short-term", "ideas": "short-term", "crypto": "short-term",
    "opportunity": "long-term",
}


def horizon_for_model(model_id: str) -> str:
    """The horizon a model runs on, from its edge's real holding period."""
    return MODEL_HORIZON.get(model_id, "short-term")


def prediction_times(when: datetime | None = None) -> dict[str, datetime]:
    """When each horizon's predictions are made for the next session: 12h before
    open (long-term) / 6h before open (short-term). Returned in UTC, keyed by
    horizon. No intra-day — the two horizons match where the edges were measured.
    """
    from datetime import timedelta
    now = _now(when)
    open_utc = next_open(ANCHOR, now)
    return {h: open_utc - timedelta(hours=lead)
            for h, lead in PREDICTION_LEAD_HOURS.items()}


def horizon_lead_line(horizon: str, when: datetime | None = None) -> str:
    """A page label: when this horizon's predictions are made and the gap to open."""
    lead = PREDICTION_LEAD_HOURS.get(horizon, 6)
    times = prediction_times(when)
    t = times.get(horizon)
    if t is None:
        return ""
    local = t.astimezone(ANCHOR_TZ)
    return f"made {lead}h before open · {local:%d %b %H:%M} IST"


def should_show_predictions(when: datetime | None = None) -> bool:
    """Predictions page shows content only after they're made and before reset."""
    return cycle_state(when).phase in (Phase.PREDICT, Phase.TRADE, Phase.CLOSED)


def should_trade(when: datetime | None = None) -> bool:
    """Paper trading places trades only while the anchor market is open."""
    return cycle_state(when).phase is Phase.TRADE


def reset_line(when: datetime | None = None) -> str:
    """Human-readable reset time for the page footer."""
    st = cycle_state(when)
    local = st.reset_at.astimezone(ANCHOR_TZ)
    return f"Resets {local:%d %b %H:%M} IST (one hour after the NSE close)"


def model_timing_summary() -> str:
    """Per-model: which horizon, when predictions are made, and the lock — so the
    schedule is transparent and matches each edge's real mechanics."""
    lines = ["PER-MODEL TIMING (decided by each edge's real holding period)", ""]
    for model, horizon in MODEL_HORIZON.items():
        lead = PREDICTION_LEAD_HOURS.get(horizon, 6)
        lines.append(f"  {model:<11} [{horizon}] — made & LOCKED {lead}h before "
                     "open, then only resolves into a result/trade")
    lines.append("")
    lines.append("Long-term (stocks, ventures): 12h lead — fundamental/slow, an")
    lines.append("early lock is fine. Short-term (news, ideas, crypto): 6h lead —")
    lines.append("event-driven, a fresher call locked closer to the open.")
    return "\n".join(lines)
