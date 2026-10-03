"""Market-aware 24/7 scheduler — always awake, predicts only when legitimate.

SIGBOT never sleeps, but a scheduler wake-up is not a prediction. This layer
decides WHICH models may do WHAT at a given moment, based on market state and an
event taxonomy. It does not decide whether a candidate is a valid prediction —
that is the admission gate's job. Increasing scheduler frequency therefore can
never turn into database spam.

TWO CORRECTIONS FROM THE SPEC, built into the contract here:

  1. INFORMATION TIMESTAMPS, not just construction time. A PredictAction carries
     information_as_of (when the data was knowable), decision_effective_at (the
     session execution point — e.g. next NSE open for an overnight stocks call),
     and the outcome window. "Before the move" means the information predates the
     outcome window, and the trade is measured from its real execution point, not
     from the moment the scanner happened to wake.

  2. EVENT-SPECIFIC NEWS KEY. News carries event_id so two distinct events on one
     asset are two predictions, while the same event re-seen is one.

THE EVENT TAXONOMY (the structural rule): every scheduler event is exactly one of
SCAN / RESEARCH / PREPARE / PREDICT / RESOLVE / MONITOR / RECOVER. ONLY a PREDICT
event can produce a prediction — and even then only through admission. So 10,000
wake-ups can legitimately produce zero predictions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .market_hours import Venue, is_open, next_open


# ── the event taxonomy ──────────────────────────────────────────────────────
class EventType(str, Enum):
    SCAN = "scan"             # look for setups — never records
    RESEARCH = "research"     # generate/test hypotheses — never records
    PREPARE = "prepare"       # pre-session data prep — never records
    PREDICT = "predict"       # the ONLY type that can produce a prediction
    RESOLVE = "resolve"       # score matured predictions — never records
    MONITOR = "monitor"       # health/pipeline checks — never records
    RECOVER = "recover"       # post-quarantine recovery — never records


# only PREDICT may create a prediction. Enforced by can_create_prediction().
_PREDICTION_CAPABLE = frozenset({EventType.PREDICT})


def can_create_prediction(event_type: EventType) -> bool:
    return event_type in _PREDICTION_CAPABLE


# ── market state ────────────────────────────────────────────────────────────
class MarketPhase(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    PREOPEN = "preopen"        # within the prep window before an equity open


@dataclass(frozen=True)
class MarketState:
    equities_phase: MarketPhase     # NSE/NYSE aggregate
    crypto_open: bool               # effectively always true
    now: datetime

    @staticmethod
    def observe(now: datetime | None = None,
                preopen_window_h: float = 2.0) -> "MarketState":
        now = now or datetime.now(timezone.utc)
        nse = is_open(Venue.NSE, now)
        nyse = is_open(Venue.NYSE, now)
        if nse or nyse:
            phase = MarketPhase.OPEN
        else:
            # pre-open if within the window before either venue's next open
            nse_in = (next_open(Venue.NSE, now) - now).total_seconds() / 3600
            nyse_in = (next_open(Venue.NYSE, now) - now).total_seconds() / 3600
            soonest = min(nse_in, nyse_in)
            phase = (MarketPhase.PREOPEN if 0 <= soonest <= preopen_window_h
                     else MarketPhase.CLOSED)
        return MarketState(phase, is_open(Venue.CRYPTO, now), now)


# ── model families and their clocks ─────────────────────────────────────────
class Family(str, Enum):
    STOCKS = "stocks"
    NEWS = "news"
    CRYPTO = "crypto"
    VENTURES = "ventures"
    IDEAS = "ideas"


class Priority(str, Enum):
    BACKGROUND = "background"
    EVENT_DRIVEN = "event_driven"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class FamilyBudget:
    """Service-level budget so no family is ever starved to nothing."""
    minimum: Priority
    normal: Priority
    boost_conditions: tuple[str, ...]


BUDGETS = {
    Family.STOCKS: FamilyBudget(Priority.BACKGROUND, Priority.HIGH,
                                ("preopen", "active_setup")),
    Family.NEWS: FamilyBudget(Priority.EVENT_DRIVEN, Priority.EVENT_DRIVEN,
                              ("event_burst",)),
    Family.CRYPTO: FamilyBudget(Priority.NORMAL, Priority.NORMAL,
                                ("elevated_activity",)),
    Family.VENTURES: FamilyBudget(Priority.BACKGROUND, Priority.NORMAL,
                                  ("equities_closed", "research_backlog")),
    Family.IDEAS: FamilyBudget(Priority.BACKGROUND, Priority.NORMAL,
                               ("equities_closed", "new_opportunity")),
}


def priority_for(family: Family, state: MarketState,
                 event_queue: int = 0, backlog: int = 0) -> Priority:
    """Market- and workload-aware priority. Defaults by market phase, with boosts
    when real work is waiting — never below the family's minimum."""
    b = BUDGETS[family]
    equities_open = state.equities_phase == MarketPhase.OPEN

    if family == Family.STOCKS:
        if state.equities_phase == MarketPhase.PREOPEN:
            p = Priority.HIGH          # boost: prepare next-session candidates
        elif equities_open:
            p = Priority.HIGH
        else:
            p = Priority.BACKGROUND    # post-close: resolve/research only
    elif family == Family.NEWS:
        p = Priority.HIGH if event_queue >= 10 else Priority.EVENT_DRIVEN
    elif family == Family.CRYPTO:
        p = Priority.HIGH if not equities_open else Priority.NORMAL
    elif family in (Family.VENTURES, Family.IDEAS):
        if not equities_open:
            p = Priority.HIGH          # shift research here when equities closed
        elif backlog >= 20:
            p = Priority.NORMAL        # backlog boost even during session
        else:
            p = Priority.BACKGROUND
    else:
        p = b.normal

    # never below the floor
    order = [Priority.BACKGROUND, Priority.EVENT_DRIVEN, Priority.NORMAL,
             Priority.HIGH]
    if order.index(p) < order.index(b.minimum):
        p = b.minimum
    return p


# ── what a PREDICT event must carry (the corrected timestamp contract) ──────
@dataclass(frozen=True)
class PredictAction:
    """A PREDICT event's payload. Carries the full information/decision/outcome
    timestamp chain so the admission gate can prove no look-ahead AND that the
    trade is measured from its real execution point."""
    family: Family
    symbol: str
    information_as_of: datetime       # when the data was knowable
    prediction_created_at: datetime   # when the model made the call
    decision_effective_at: datetime   # session execution point (e.g. next open)
    outcome_start: datetime           # == decision_effective_at for most
    outcome_end: datetime
    event_id: str = ""                # News: distinguishes distinct events
    horizon: str = ""

    def dedup_key(self) -> str:
        if self.family == Family.NEWS:
            return f"news|{self.event_id}|{self.symbol}|{self.horizon}"
        if self.family == Family.STOCKS:
            return f"stocks|{self.symbol}|{self.horizon}"
        if self.family == Family.CRYPTO:
            return f"crypto|{self.symbol}|{self.horizon}"
        if self.family == Family.VENTURES:
            return f"ventures|{self.symbol}|{self.horizon}"
        return f"ideas|{self.symbol}|{self.horizon}"

    def timestamps_valid(self) -> bool:
        """information <= created <= decision_effective = outcome_start < end,
        and information strictly before the outcome window."""
        return (self.information_as_of <= self.prediction_created_at
                <= self.decision_effective_at
                and self.decision_effective_at == self.outcome_start
                and self.outcome_start < self.outcome_end
                and self.information_as_of < self.outcome_start)


# ── a scheduled event ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class ScheduledEvent:
    family: Family
    event_type: EventType
    priority: Priority
    predict_action: PredictAction | None = None


# ── the scheduler: decides what each family may do now ──────────────────────
@dataclass
class MarketScheduler:
    """At each wake, produces the events each family is allowed to run now. It
    assigns event TYPES by market phase; only PREDICT events (produced when a
    family's market is open to predictions) can eventually create a prediction."""
    preopen_window_h: float = 2.0

    def plan_tick(self, now: datetime | None = None,
                  news_queue: int = 0, ventures_backlog: int = 0,
                  ideas_backlog: int = 0) -> list[ScheduledEvent]:
        state = MarketState.observe(now, self.preopen_window_h)
        events: list[ScheduledEvent] = []

        # STOCKS: session-aware
        s_pri = priority_for(Family.STOCKS, state)
        if state.equities_phase == MarketPhase.PREOPEN:
            events.append(ScheduledEvent(Family.STOCKS, EventType.PREPARE, s_pri))
        elif state.equities_phase == MarketPhase.OPEN:
            events.append(ScheduledEvent(Family.STOCKS, EventType.PREDICT, s_pri))
        else:  # CLOSED
            events.append(ScheduledEvent(Family.STOCKS, EventType.RESOLVE, s_pri))
            events.append(ScheduledEvent(Family.STOCKS, EventType.RESEARCH,
                                         Priority.BACKGROUND))

        # NEWS: event-driven — only a PREDICT when there is an event to act on
        n_pri = priority_for(Family.NEWS, state, event_queue=news_queue)
        if news_queue > 0:
            events.append(ScheduledEvent(Family.NEWS, EventType.PREDICT, n_pri))
        else:
            events.append(ScheduledEvent(Family.NEWS, EventType.MONITOR, n_pri))

        # CRYPTO: continuous
        c_pri = priority_for(Family.CRYPTO, state)
        if state.crypto_open:
            events.append(ScheduledEvent(Family.CRYPTO, EventType.PREDICT, c_pri))

        # VENTURES / IDEAS: research-driven, more when equities closed
        v_pri = priority_for(Family.VENTURES, state, backlog=ventures_backlog)
        events.append(ScheduledEvent(Family.VENTURES, EventType.RESEARCH, v_pri))
        if ventures_backlog > 0:
            events.append(ScheduledEvent(Family.VENTURES, EventType.PREDICT, v_pri))

        i_pri = priority_for(Family.IDEAS, state, backlog=ideas_backlog)
        events.append(ScheduledEvent(Family.IDEAS, EventType.RESEARCH, i_pri))
        if ideas_backlog > 0:
            events.append(ScheduledEvent(Family.IDEAS, EventType.PREDICT, i_pri))

        return events

    def current_allocation(self, now: datetime | None = None,
                           news_queue: int = 0, ventures_backlog: int = 0,
                           ideas_backlog: int = 0) -> dict[str, str]:
        """The live priority map the website/API renders — from scheduler state,
        never hand-typed."""
        state = MarketState.observe(now, self.preopen_window_h)
        return {
            "equities": state.equities_phase.value,
            "crypto": "open" if state.crypto_open else "closed",
            "stocks": priority_for(Family.STOCKS, state).value,
            "news": priority_for(Family.NEWS, state, event_queue=news_queue).value,
            "crypto_priority": priority_for(Family.CRYPTO, state).value,
            "ventures": priority_for(Family.VENTURES, state,
                                     backlog=ventures_backlog).value,
            "ideas": priority_for(Family.IDEAS, state, backlog=ideas_backlog).value,
        }


def describe() -> str:
    return "\n".join([
        "MARKET-AWARE SCHEDULER — always awake, predicts only when legitimate",
        "",
        "  Decides WHICH family does WHAT now by market phase; it does NOT decide",
        "  what's a valid prediction (admission does). So more frequent wakes",
        "  cannot become database spam.",
        "",
        "  EVENT TAXONOMY: every event is SCAN/RESEARCH/PREPARE/PREDICT/RESOLVE/",
        "  MONITOR/RECOVER. ONLY PREDICT can produce a prediction — and only",
        "  through admission. 10,000 wakes can produce zero predictions.",
        "",
        "  CLOCKS: stocks session-aware (PREPARE preopen / PREDICT open / RESOLVE",
        "  +RESEARCH closed); news event-driven (PREDICT only with a queued",
        "  event); crypto continuous; ventures/ideas research-driven, boosted",
        "  when equities close. Service-level budgets keep every family above a",
        "  minimum — none is ever starved. PredictAction carries the full",
        "  information/decision/outcome timestamp chain, and News carries event_id.",
    ])
