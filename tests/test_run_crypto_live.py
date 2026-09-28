"""Live crypto runner — records real, resolvable coiled-spring predictions."""
import random
import sqlite3
from contextlib import closing

import pandas as pd


def _coiled_provider():
    """A provider whose coins show the coiled-spring pattern (calm + volume)."""
    random.seed(1)

    class P:
        def history(self, coin, days=40):
            closes = [100.0]
            for _ in range(27):
                closes.append(closes[-1] * (1 + random.uniform(-0.03, 0.03)))
            for _ in range(5):
                closes.append(closes[-1] * (1 + random.uniform(-0.003, 0.003)))
            vols = [1e6] * 28 + [3e6, 3.5e6, 4e6, 4.2e6, 4.5e6]
            return pd.DataFrame({"close": closes, "volume": vols})
    return P()


def test_crypto_records_real_resolvable_predictions(tmp_path):
    from sigbot.run_crypto_live import run_crypto_live
    from sigbot.shadow import ShadowLedger

    db = tmp_path / "ledger.db"
    ledger = ShadowLedger(str(db))

    class S:
        shadow_db = str(db)

    run_crypto_live(settings=S(), provider=_coiled_provider(), ledger=ledger,
                   inter_request_sleep=0)

    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT model, symbol, entry_price, resolve_after FROM predictions "
            "WHERE model='crypto'").fetchall()
    assert rows, "crypto should record real predictions on coiled coins"
    for model, _symbol, entry, resolve_after in rows:
        assert model == "crypto"
        assert entry and entry > 0          # a real entry price
        assert resolve_after                # a real resolution time (checkable)


def test_a_flat_market_records_nothing(tmp_path):
    """No coiled-and-loaded setup -> no prediction (honest, not forced)."""
    from sigbot.run_crypto_live import run_crypto_live
    from sigbot.shadow import ShadowLedger

    class Flat:
        def history(self, coin, days=40):
            return pd.DataFrame({"close": [100.0] * 40, "volume": [1e6] * 40})

    db = tmp_path / "ledger.db"
    ledger = ShadowLedger(str(db))

    class S:
        shadow_db = str(db)

    run_crypto_live(settings=S(), provider=Flat(), ledger=ledger,
                   inter_request_sleep=0)
    with closing(sqlite3.connect(db)) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE model='crypto'").fetchone()[0]
    assert n == 0                            # nothing forced
