"""Live ventures runner — records real sustained-inflection predictions.

Wires the forward-tested venture edge (sustained margin+growth acceleration in a
capital-efficient company) to live SEC EDGAR fundamentals and records real,
resolvable predictions with a stock entry price and a long-term horizon.

Per cycle: for a watchlist of growth companies, pull their SEC fundamentals
(revenue-growth and gross-margin series), test sustained_inflection, and when it
fires record a prediction (entry = today's stock price, 90-day horizon — the
edge's real hold). The resolver scores it hit/miss on the realised move.
"""
from __future__ import annotations

from .sustained_inflection import sustained_inflection

HORIZON_HOURS = 90 * 24        # 90-day hold — the venture inflection's horizon

# (ticker, CIK) for a growth-company watchlist. CIKs are SEC's company ids.
# A starter set of liquid growth names; extend as the board rotates.
VENTURE_WATCHLIST = [
    ("NVDA", "1045810"), ("CRM", "1108524"), ("NOW", "1373715"),
    ("SNOW", "1640147"), ("DDOG", "1561550"), ("NET", "1477333"),
    ("CRWD", "1535527"), ("ZS", "1713683"), ("PLTR", "1321655"),
    ("SHOP", "1594805"), ("MDB", "1441816"), ("TEAM", "1650372"),
]


def run_ventures_live(settings=None, sec=None, price_of=None, ledger=None) -> str:
    """Scan the venture watchlist, record a real prediction for each company
    showing a sustained operating inflection. Returns a one-line summary."""
    from .config import SETTINGS
    from .providers import sec_edgar
    from .providers.market import YahooProvider
    from .shadow import ShadowLedger

    settings = settings or SETTINGS
    ledger = ledger or ShadowLedger(settings.shadow_db)

    def _default_price(ticker: str) -> float | None:
        try:
            df = YahooProvider(retries=1).history(
                ticker, "2020-01-01", "2035-01-01")
            return float(df["close"].iloc[-1]) if df is not None and len(df) else None
        except Exception:  # noqa: BLE001
            from .skips import record_skip
            record_skip("ventures_live_price", ticker, Exception("price fetch"))
            return None

    price_of = price_of or _default_price
    fired = 0
    scanned = 0
    for ticker, cik in VENTURE_WATCHLIST:
        try:
            f = (sec or sec_edgar).fundamentals(cik)
        except Exception as exc:  # noqa: BLE001
            from .skips import record_skip
            record_skip("ventures_live", ticker, exc)
            continue
        scanned += 1
        # sustained_inflection wants 4 gross margins + 3 revenue growths.
        read = sustained_inflection(
            gross_margins=f.gross_margins[-4:] if len(f.gross_margins) >= 4 else None,
            revenue_growths=f.revenue_growths[-3:] if len(f.revenue_growths) >= 3 else None)
        if not read.is_inflection:
            continue
        entry = price_of(ticker)
        if entry is None or entry <= 0:
            continue
        ledger.record(
            model="ventures", symbol=ticker, side="BUY",
            score=None, expected_move=0.20, entry_price=entry,
            horizon_hours=HORIZON_HOURS,
            payload=f"sustained inflection: {read.note}")
        fired += 1
    return (f"ventures: scanned {scanned}, {fired} sustained-inflection "
            "prediction(s) recorded (90-day horizon, resolves on the move)")


if __name__ == "__main__":
    print(run_ventures_live())
