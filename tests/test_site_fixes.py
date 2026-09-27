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


def test_each_model_horizon_matches_its_edge():
    """Timing decided by edge mechanics: fundamentals long, events short."""
    from sigbot.daily_cycle import horizon_for_model
    assert horizon_for_model("stocks") == "long-term"      # quarterly inflection
    assert horizon_for_model("ventures") == "long-term"    # 90-day hold
    assert horizon_for_model("news") == "short-term"       # 5-10d drift
    assert horizon_for_model("ideas") == "short-term"      # 10d catalyst
    assert horizon_for_model("crypto") == "short-term"     # 3d coiled-spring


def test_long_term_window_exceeds_short_term():
    """Long-term models hold longer than short-term — windows must reflect it."""
    from sigbot.daily_cycle import MODEL_HORIZON
    from sigbot.report import SIGNAL_WINDOW_DAYS
    long_windows = [SIGNAL_WINDOW_DAYS[m] for m, h in MODEL_HORIZON.items()
                    if h == "long-term" and m in SIGNAL_WINDOW_DAYS]
    short_windows = [SIGNAL_WINDOW_DAYS[m] for m, h in MODEL_HORIZON.items()
                     if h == "short-term" and m in SIGNAL_WINDOW_DAYS]
    assert min(long_windows) >= max(short_windows)         # long >= short


def test_timing_summary_lists_every_model():
    from sigbot.daily_cycle import model_timing_summary
    out = model_timing_summary()
    for m in ("stocks", "ventures", "news", "ideas", "crypto"):
        assert m in out
    assert "LOCKED" in out
