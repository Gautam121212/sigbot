"""The daily cycle: predictions before open, trade at open, reset at a fixed time."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sigbot.daily_cycle import Phase, cycle_state, reset_line, should_trade

IST = ZoneInfo("Asia/Kolkata")


def _at(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


def test_market_open_is_the_trade_phase():
    # A Monday during NSE hours (10:00 IST).
    st = cycle_state(_at(2026, 9, 28, 10))
    assert st.phase is Phase.TRADE
    assert st.predictions_locked is True
    assert should_trade(_at(2026, 9, 28, 10))


def test_after_reset_is_the_predict_phase_for_next_day():
    # 8pm IST Monday: after the 16:30 reset, predicting for Tuesday.
    st = cycle_state(_at(2026, 9, 28, 20))
    assert st.phase is Phase.PREDICT
    assert not st.predictions_locked
    assert st.trading_day == "2026-09-29"


def test_pre_open_morning_is_predict_and_not_locked():
    # 8am IST Monday: before the 9:15 open, predictions still open for today.
    st = cycle_state(_at(2026, 9, 28, 8))
    assert st.phase is Phase.PREDICT
    assert not st.predictions_locked


def test_predictions_lock_once_the_market_opens():
    assert cycle_state(_at(2026, 9, 28, 10)).predictions_locked
    assert not cycle_state(_at(2026, 9, 28, 8)).predictions_locked


def test_reset_line_names_the_time():
    line = reset_line(_at(2026, 9, 28, 20))
    assert "Resets" in line and "IST" in line


def test_trading_day_is_the_next_open_date():
    # Friday evening -> next open is Monday.
    st = cycle_state(_at(2026, 9, 25, 20))
    assert st.trading_day == "2026-09-28"
