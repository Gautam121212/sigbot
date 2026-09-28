"""Live ideas runner — records real volatile-catalyst predictions from 8-Ks.

Wires the forward-tested ideas edge (a material-agreement catalyst on an already-
volatile small/mid-cap) to live SEC 8-K filings and records real, resolvable
predictions — replacing the news-scraper cards that never resolved.

Per cycle: for a watchlist of small/mid-cap companies, pull their recent 8-K
filings from SEC EDGAR. When a company filed a material agreement (item 1.01)
RECENTLY and its stock is currently volatile (ATR/price high), record a
prediction (entry = today's price, 10-day horizon — the catalyst move's real
window). The resolver scores it hit/miss on the realised move.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .deep_edges_2 import volatile_catalyst

HORIZON_HOURS = 10 * 24        # 10-day catalyst window
MATERIAL_AGREEMENT = "1.01"    # the 8-K item that drives the edge
RECENT_DAYS = 7                # act on a filing within the last 7 days (3 was too tight)

# (ticker, CIK) for a small/mid-cap watchlist where catalysts move stocks.
IDEAS_WATCHLIST = [
    # Quantum / AI / Space — high-volatility small-caps, frequent 8-K deals
    ("IONQ", "1824920"), ("RGTI", "1838831"), ("QBTS", "1860742"),
    ("SOUN", "1844505"), ("BBAI", "1836981"), ("RKLB", "1819994"),
    ("ASTS", "1780312"), ("ACHR", "1824644"), ("JOBY", "1819848"),
    ("LUNR", "1844452"), ("RXRX", "1601830"), ("DNA", "1830214"),
    # BioTech / MedTech — frequent material agreements (licensing, partnerships)
    ("ARQT", "1673139"), ("BEAM", "1689548"), ("CRSP", "1674930"),
    ("EDIT", "1480572"), ("FATE", "1340652"), ("NTLA", "1617898"),
    ("PCVX", "1756497"), ("RCKT", "1516108"), ("RARE", "1574085"),
    # EV / Clean energy — deal-heavy, volatile
    ("CHPT", "1819989"), ("FSR", "1731480"), ("GOEV", "1750153"),
    ("HYLN", "1759774"), ("NKLA", "1628369"), ("RIDE", "1750153"),
]


def _is_volatile(ticker: str, price_hist) -> tuple[bool, float | None, float | None]:
    """Is the stock currently volatile, and what is its price + market cap proxy.
    Returns (volatile, price, atr_pct). Uses ~20 days of history."""
    if price_hist is None or len(price_hist) < 20:
        return False, None, None
    closes = [float(x) for x in price_hist["close"].tolist()[-20:]]
    price = closes[-1]
    moves = [abs(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    atr_pct = sum(moves) / len(moves) if moves else 0.0
    return atr_pct > 0.06, price, atr_pct


def run_ideas_live(settings=None, sec=None, hist_of=None, ledger=None) -> str:
    """Scan the ideas watchlist for recent material-agreement 8-Ks on volatile
    small-caps, record a real prediction for each. Returns a one-line summary."""
    from .config import SETTINGS
    from .providers import sec_edgar
    from .providers.market import YahooProvider
    from .shadow import ShadowLedger

    settings = settings or SETTINGS
    ledger = ledger or ShadowLedger(settings.shadow_db)

    def _default_hist(ticker: str):
        try:
            return YahooProvider(retries=1).history(
                ticker, "2020-01-01", "2035-01-01")
        except Exception:  # noqa: BLE001
            from .skips import record_skip
            record_skip("ideas_live_hist", ticker, Exception("hist fetch"))
            return None

    hist_of = hist_of or _default_hist
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).date()
    fired = 0
    scanned = 0
    for ticker, cik in IDEAS_WATCHLIST:
        try:
            filings = (sec or sec_edgar).recent_8k(cik)
        except Exception as exc:  # noqa: BLE001
            from .skips import record_skip
            record_skip("ideas_live", ticker, exc)
            continue
        scanned += 1
        # a RECENT material-agreement filing?
        has_recent_deal = False
        for fil in filings:
            if MATERIAL_AGREEMENT not in fil.items:
                continue
            try:
                fdate = datetime.strptime(fil.filing_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if fdate >= cutoff:
                has_recent_deal = True
                break
        if not has_recent_deal:
            continue
        hist = hist_of(ticker)
        volatile, price, atr_pct = _is_volatile(ticker, hist)
        read = volatile_catalyst(has_material_agreement=True, atr_pct=atr_pct,
                                 market_cap=1e9)   # watchlist is small/mid-cap
        if not read.is_live_catalyst or price is None:
            continue
        ledger.record(
            model="opportunity", symbol=ticker, side="BUY",
            score=read.big_move_prob, expected_move=0.15, entry_price=price,
            horizon_hours=HORIZON_HOURS,
            payload=f"volatile catalyst (8-K material agreement): {read.note}")
        fired += 1
    return (f"ideas: scanned {scanned}, {fired} volatile-catalyst prediction(s) "
            "recorded (10-day horizon, resolves on the move)")


if __name__ == "__main__":
    print(run_ideas_live())
