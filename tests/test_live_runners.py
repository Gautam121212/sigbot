"""Live ventures and ideas runners — real, resolvable predictions from SEC data."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import pandas as pd

from sigbot.providers.sec_edgar import Filing, Fundamentals
from sigbot.shadow import ShadowLedger


def test_ventures_records_real_inflection_predictions(tmp_path):
    from sigbot.run_ventures_live import run_ventures_live

    db = tmp_path / "l.db"
    ledger = ShadowLedger(str(db))

    class S:
        shadow_db = str(db)

    class Sec:
        def fundamentals(self, cik):
            return Fundamentals(cik=cik, revenue_growths=[0.20, 0.28, 0.38],
                                gross_margins=[0.55, 0.58, 0.61, 0.64])

    run_ventures_live(settings=S(), sec=Sec(), price_of=lambda t: 100.0,
                      ledger=ledger)
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT entry_price, resolve_after FROM predictions "
            "WHERE model='ventures'").fetchall()
    assert rows                              # real predictions recorded
    assert all(e and e > 0 for e, _ in rows)  # real entry prices


def test_ventures_no_inflection_records_nothing(tmp_path):
    from sigbot.run_ventures_live import run_ventures_live

    db = tmp_path / "l.db"

    class S:
        shadow_db = str(db)

    class Sec:
        def fundamentals(self, cik):
            # margins FALLING — not an inflection
            return Fundamentals(cik=cik, revenue_growths=[0.38, 0.28, 0.20],
                                gross_margins=[0.64, 0.61, 0.58, 0.55])

    run_ventures_live(settings=S(), sec=Sec(), price_of=lambda t: 100.0,
                      ledger=ShadowLedger(str(db)))
    with closing(sqlite3.connect(db)) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE model='ventures'").fetchone()[0]
    assert n == 0                            # nothing forced


def test_ideas_is_disabled_until_edge_is_fixed(tmp_path):
    """Ideas failed trade-level validation (median trade -3.31%), so the live
    runner refuses to record predictions until rebuilt with 8-K classification."""
    from sigbot.run_ideas_live import run_ideas_live
    result = run_ideas_live()
    assert "DISABLED" in result
    return  # the rest of the old test (expecting records) no longer applies


def _test_ideas_records_real_catalyst_predictions_DISABLED(tmp_path):
    from sigbot.run_ideas_live import run_ideas_live

    db = tmp_path / "l.db"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    class S:
        shadow_db = str(db)

    class Sec:
        def recent_8k(self, cik):
            return [Filing(cik=cik, form="8-K", filing_date=today,
                           items=["1.01"], accession="x")]

    # genuinely volatile stock (~7.5% avg daily move)
    closes = [100.0]
    for i in range(25):
        closes.append(closes[-1] * (1.08 if i % 2 == 0 else 0.93))
    hist = pd.DataFrame({"close": closes})

    run_ideas_live(settings=S(), sec=Sec(), hist_of=lambda t: hist,
                   ledger=ShadowLedger(str(db)))
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT entry_price FROM predictions WHERE model='opportunity'"
        ).fetchall()
    assert rows                              # real predictions recorded


def test_ideas_quiet_stock_records_nothing(tmp_path):
    from sigbot.run_ideas_live import run_ideas_live

    db = tmp_path / "l.db"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    class S:
        shadow_db = str(db)

    class Sec:
        def recent_8k(self, cik):
            return [Filing(cik=cik, form="8-K", filing_date=today,
                           items=["1.01"], accession="x")]

    hist = pd.DataFrame({"close": [100.0] * 26})   # dead flat — not volatile
    run_ideas_live(settings=S(), sec=Sec(), hist_of=lambda t: hist,
                   ledger=ShadowLedger(str(db)))
    with closing(sqlite3.connect(db)) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE model='opportunity'"
        ).fetchone()[0]
    assert n == 0                            # quiet stock -> no catalyst trade


def test_all_five_models_scheduled():
    """After Commit B, the five old prediction runners are replaced by the single
    OperatingLoop job. The old names leave the schedule; the loop covers all five."""
    from sigbot.coordinator import JOBS, _LOOP_ENABLED
    names = [j[0] for j in JOBS]
    # old individual runners no longer in schedule — loop covers them
    for old in ("stocks", "news", "crypto", "ventures", "ideas"):
        assert old not in names, f"old prediction job '{old}' still in schedule"
    assert "operating_loop" in names          # the single new path
    assert _LOOP_ENABLED is True
