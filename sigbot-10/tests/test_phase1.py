"""Phase 1: point-in-time storage, input validation, and the lint guarantees."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from sigbot.pit_store import PitStore
from sigbot.sanitize import (
    NEWS_ITEM, PRICE_BAR, TELEGRAM_UPDATE, WEBHOOK_CONFIG, Rejected,
    validate_bar, validate_many, validate_news,
)

T0 = datetime(2026, 1, 10, tzinfo=timezone.utc)
T1 = datetime(2026, 6, 10, tzinfo=timezone.utc)


def _frame(n=10, close=100.0):
    idx = pd.bdate_range("2025-01-01", periods=n)
    c = np.full(n, close)
    return pd.DataFrame(dict(open=c, high=c * 1.01, low=c * 0.99, close=c,
                             volume=np.full(n, 1e6)), index=idx)


@pytest.fixture
def store(tmp_path):
    return PitStore(tmp_path / "pit.db")


# ------------------------------------------------- the point-in-time property

def test_a_later_split_does_not_change_the_earlier_view(store):
    """The whole reason this exists: a backtest as of January must see January
    prices, not the values Yahoo rewrote them to in June."""
    store.insert_frame("AAPL", _frame(close=200.0), "yahoo", downloaded_at=T0)
    store.insert_frame("AAPL", _frame(close=50.0), "yahoo", downloaded_at=T1)  # 4:1 split

    as_january = store.get_bars("AAPL", as_of=T0)
    as_june = store.get_bars("AAPL", as_of=T1)
    assert as_january["close"].iloc[0] == 200.0
    assert as_june["close"].iloc[0] == 50.0
    assert store.get_bars("AAPL")["close"].iloc[0] == 50.0, "no as_of means newest"


def test_reading_without_as_of_is_the_contaminated_view(store):
    """Named so it is obvious in a failure: this is the trap, not the fix."""
    store.insert_frame("X", _frame(close=100.0), "yahoo", downloaded_at=T0)
    store.insert_frame("X", _frame(close=25.0), "yahoo", downloaded_at=T1)
    assert store.get_bars("X").equals(store.get_bars("X", as_of=T1))


def test_unchanged_refetches_cost_nothing(store):
    frame = _frame()
    assert store.insert_frame("X", frame, "yahoo", downloaded_at=T0) == 10
    assert store.insert_frame("X", frame, "yahoo", downloaded_at=T1) == 0
    assert store.coverage("X")["snapshots"] == 10


def test_only_changed_bars_are_rewritten(store):
    store.insert_frame("X", _frame(), "yahoo", downloaded_at=T0)
    changed = _frame()
    changed.iloc[3, changed.columns.get_loc("close")] = 111.0
    assert store.insert_frame("X", changed, "yahoo", downloaded_at=T1) == 1


def test_every_snapshot_of_a_bar_is_retrievable(store):
    store.insert_frame("X", _frame(close=100.0), "yahoo", downloaded_at=T0)
    store.insert_frame("X", _frame(close=50.0), "yahoo", downloaded_at=T1)
    snaps = store.snapshots("X", pd.Timestamp("2025-01-01").isoformat())
    assert len(snaps) == 2
    assert [s["close"] for s in snaps] == [100.0, 50.0]


def test_rewrites_are_detected_and_explained(store):
    store.insert_frame("AAPL", _frame(close=200.0), "yahoo", downloaded_at=T0)
    store.insert_frame("AAPL", _frame(close=50.0), "yahoo", downloaded_at=T1)
    found = store.rewrites("AAPL")
    assert len(found) == 10
    r = found[0]
    assert r.was == 200.0 and r.now == 50.0
    assert r.ratio == pytest.approx(0.25)
    assert "split or dividend" in r.render()


def test_no_rewrites_when_nothing_changed(store):
    store.insert_frame("X", _frame(), "yahoo", downloaded_at=T0)
    store.insert_frame("X", _frame(), "yahoo", downloaded_at=T1)
    assert store.rewrites("X") == []


def test_a_frame_missing_columns_is_refused(store):
    with pytest.raises(ValueError, match="missing"):
        store.insert_frame("X", _frame().drop(columns=["volume"]), "yahoo")


def test_empty_and_unknown_reads_are_empty_not_errors(store):
    assert store.insert_frame("X", pd.DataFrame(), "yahoo") == 0
    assert store.get_bars("NEVER_SEEN").empty
    assert store.assets() == []


def test_summary_says_it_cannot_reach_backwards(store):
    assert "cannot reach backwards" in store.summary()
    store.insert_frame("X", _frame(), "yahoo", downloaded_at=T0)
    assert "No rewrites detected yet" in store.summary()


def test_date_range_filtering(store):
    store.insert_frame("X", _frame(20), "yahoo", downloaded_at=T0)
    all_bars = store.get_bars("X")
    # Bounds are compared as ISO strings, so pass them in the stored form.
    subset = store.get_bars("X", start=all_bars.index[5].isoformat(),
                            end=all_bars.index[9].isoformat())
    assert len(subset) == 5


# ----------------------------------------------------------- validation

def test_a_good_bar_validates():
    assert validate_bar({"timestamp": "2026-01-01T00:00:00", "open": 1.0,
                         "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100})


@pytest.mark.parametrize("field", ["timestamp", "open", "close", "volume"])
def test_a_missing_required_field_is_rejected(field):
    payload = {"timestamp": "2026-01-01T00:00:00", "open": 1.0, "high": 2.0,
               "low": 0.5, "close": 1.5, "volume": 100}
    payload.pop(field)
    with pytest.raises(Rejected, match="missing required"):
        validate_bar(payload)


def test_an_unexpected_field_is_rejected_not_dropped():
    """A provider that starts sending something new has changed its contract.
    Dropping it silently means finding out months later."""
    payload = {"timestamp": "2026-01-01T00:00:00", "open": 1.0, "high": 2.0,
               "low": 0.5, "close": 1.5, "volume": 100, "surprise": "hello"}
    with pytest.raises(Rejected, match="unexpected field"):
        validate_bar(payload)


def test_wrong_types_are_rejected():
    base = {"timestamp": "2026-01-01T00:00:00", "open": 1.0, "high": 2.0,
            "low": 0.5, "close": 1.5, "volume": 100}
    with pytest.raises(Rejected, match="expected int/float"):
        validate_bar({**base, "close": "1.5"})
    with pytest.raises(Rejected, match="expected str"):
        validate_bar({**base, "timestamp": 20260101})


def test_a_bool_does_not_pass_as_a_number():
    """True == 1 in Python, so a bare isinstance check would let it through."""
    base = {"timestamp": "2026-01-01T00:00:00", "open": 1.0, "high": 2.0,
            "low": 0.5, "close": 1.5, "volume": 100}
    with pytest.raises(Rejected, match="bool"):
        validate_bar({**base, "close": True})


def test_impossible_values_are_rejected():
    base = {"timestamp": "2026-01-01T00:00:00", "open": 1.0, "high": 2.0,
            "low": 0.5, "close": 1.5, "volume": 100}
    with pytest.raises(Rejected, match="above zero"):
        validate_bar({**base, "close": -1.0})
    with pytest.raises(Rejected, match="cannot be negative"):
        validate_bar({**base, "volume": -5})
    with pytest.raises(Rejected, match="ISO 8601"):
        validate_bar({**base, "timestamp": "last tuesday"})


def test_every_rejection_carries_a_reference():
    try:
        validate_bar({})
    except Rejected as exc:
        assert len(exc.ref) == 12 and exc.reasons
        assert exc.ref in str(exc)
    else:
        pytest.fail("empty payload was accepted")


def test_a_non_mapping_payload_is_rejected():
    for bad in ([1, 2], "text", None, 42):
        with pytest.raises(Rejected, match="expected a mapping"):
            PRICE_BAR.validate(bad)


def test_news_requires_an_http_link():
    good = {"title": "Nvidia beats estimates", "link": "https://x.com/a",
            "published": "2026-01-01T00:00:00"}
    assert validate_news(good)
    with pytest.raises(Rejected, match="http"):
        validate_news({**good, "link": "javascript:alert(1)"})


def test_webhook_config_refuses_anything_but_https():
    assert WEBHOOK_CONFIG.accepts({"url": "https://api.telegram.org/x"})
    assert not WEBHOOK_CONFIG.accepts({"url": "file:///etc/passwd"})
    assert not WEBHOOK_CONFIG.accepts({"url": "http://x.com"})


def test_telegram_allows_extra_fields_by_design():
    """Telegram documents new update kinds regularly; rejecting them would
    break delivery for a field we do not read."""
    assert TELEGRAM_UPDATE.accepts({"update_id": 1, "poll_answer": {"x": 1}})
    assert not TELEGRAM_UPDATE.accepts({"message": {}})     # update_id required


def test_a_batch_does_not_fail_as_a_unit():
    """One malformed RSS item must not discard the feed — and the count of
    dropped items must come back, not vanish."""
    good = {"title": "a", "link": "https://x.com", "published": "2026-01-01T00:00:00"}
    accepted, rejected = validate_many(NEWS_ITEM, [good, {"title": "b"}, good])
    assert len(accepted) == 2 and len(rejected) == 1
    assert rejected[0].ref and rejected[0].reasons


def test_rejections_are_logged_with_the_payload(caplog):
    with caplog.at_level("WARNING", logger="sigbot.sanitize"):
        with pytest.raises(Rejected):
            validate_bar({"timestamp": "x"})
    assert "rejected price_bar" in caplog.text and "payload=" in caplog.text


# ------------------------------------------------- the lint guarantees

def test_no_bare_excepts_anywhere():
    """Item 4 of Phase 1, enforced by a test rather than a CI grep, because
    there is no CI on this machine."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(["ruff", "check", "sigbot", "scripts", "--select",
                        "E722,S110,S112", "--no-cache", "--output-format=concise"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"bare or silent excepts found:\n{r.stdout}"


def test_no_january_first_date_defaults():
    """The defect in the proposed seeder: a year-only date defaulted to Jan 1,
    then measured against it."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "sigbot"
    # The defect is *deriving* a date by pinning the month and day, not passing
    # an explicit range. `history("AAPL", "2026-01-01", ...)` is a query bound;
    # `f"{year}-01-01"` invents a date the source never gave.
    import re

    invented = re.compile(r"""(f["'][^"']*\{[^}]+\}-01-01|"-01-01"|'-01-01')""")
    offenders = []
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.split("#")[0]
            if invented.search(stripped):
                offenders.append(f"{path.name}:{i}: {line.strip()[:60]}")
    assert not offenders, f"a date was invented rather than read: {offenders}"


def test_the_january_check_catches_the_real_defect():
    """Proves the check is not vacuous: the pattern from the proposed seeder."""
    import re

    invented = re.compile(r"""(f["'][^"']*\{[^}]+\}-01-01|"-01-01"|'-01-01')""")
    assert invented.search('event_date = f"{year}-01-01"')
    assert invented.search("d = year + '-01-01'")
    assert not invented.search('history("AAPL", "2026-01-01", "2030-01-01")')
    assert not invented.search('start: str = "2013-01-01"')
