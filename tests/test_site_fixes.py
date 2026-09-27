"""Site fixes — zero fresh data, daily-only count, two horizons, lock timing."""
from sigbot.daily_cycle import LOCK_BEFORE_OPEN_HOURS, PREDICTION_LEAD_HOURS


def test_only_two_horizons_no_intraday():
    assert set(PREDICTION_LEAD_HOURS) == {"long-term", "short-term"}
    assert "intra-day" not in PREDICTION_LEAD_HOURS
    assert "intraday" not in PREDICTION_LEAD_HOURS


def test_long_term_has_more_lead_than_short_term():
    assert PREDICTION_LEAD_HOURS["long-term"] > PREDICTION_LEAD_HOURS["short-term"]


def test_predictions_lock_before_open():
    # every horizon has a lock time (predictions fixed before open)
    assert LOCK_BEFORE_OPEN_HOURS["long-term"] == 12
    assert LOCK_BEFORE_OPEN_HOURS["short-term"] == 6


def test_crypto15m_retired():
    from sigbot.export_app import RETIRED_MODELS
    assert "crypto15m" in RETIRED_MODELS


def test_home_page_shows_daily_count_not_lifetime():
    """The home page 'Daily predictions' stat resets daily; no lifetime
    cumulative 'predictions checked so far' line."""
    import inspect

    from sigbot import report
    src = inspect.getsource(report.build_report)
    assert "predictions_today" in src           # daily count present
    assert "predictions checked so far" not in src   # lifetime line removed
