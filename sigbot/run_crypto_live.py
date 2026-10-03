"""Live crypto runner — records REAL, resolvable coiled-spring predictions.

Wires the forward-tested crypto movers edge (crypto_movers.py) to live CoinGecko
data and records real predictions in the ledger, so crypto shows genuine
predictions that resolve into hit/miss like stocks — not display-only cards.

THE EDGE (coiled-spring): a coin with low recent volatility AND building volume
has a ~43% chance of a 10%+ move within ~3 days. Direction-agnostic magnitude —
recorded as a volatility setup with a 3-day (72h) horizon so the resolver scores
it on the realised move.

Each cycle: pull ~40 days of daily history per coin, compute the 10d/30d range
ratio and 5d/20d volume ratio, and when a coin is coiled-and-loaded, record a
prediction with today's close as the entry and a 3-day horizon. The resolver
then marks it hit/miss on the actual move — a real, checkable record.
"""
from __future__ import annotations

from .crypto_movers import crypto_mover

# A liquid set to scan — majors plus active mid-caps (all on CoinGecko).
CRYPTO_UNIVERSE = [
    # Large-cap (always liquid)
    "bitcoin", "ethereum", "solana", "dogecoin", "shiba-inu",
    # Mid-cap DeFi + L2s
    "chainlink", "uniswap", "aave", "avalanche-2", "polkadot",
    "near", "aptos", "arbitrum", "optimism", "the-graph",
    "injective-protocol", "render-token", "sui", "sei-network",
    # Active movers with regular volatility cycles
    "algorand", "litecoin", "immutable-x", "celestia",
    "pepe", "bonk", "floki", "fantom", "tezos",
    "matic-network", "fetch-ai", "ocean-protocol", "akash-network",
]
HORIZON_HOURS = 72        # the coiled-spring releases within ~3 days
SMALL_CAP_UNDER = 5e8     # below this = very-risky tier (bigger release)


def _ranges(closes: list[float]) -> tuple[float, float]:
    """(10-day avg abs daily move, 30-day avg abs daily move)."""
    def avg_move(n: int) -> float:
        window = closes[-(n + 1):]
        if len(window) < 2:
            return 0.0
        moves = [abs(window[i] / window[i - 1] - 1) for i in range(1, len(window))]
        return sum(moves) / len(moves) if moves else 0.0
    return avg_move(10), avg_move(30)


def run_crypto_live(settings=None, provider=None, ledger=None,
                    inter_request_sleep: float = 2.5) -> str:
    """Scan the crypto universe, record a real prediction for each coiled-and-
    loaded coin. Returns a one-line summary.

    inter_request_sleep: seconds between CoinGecko requests (free tier ~30/min).
    Tests pass 0 to skip the sleep.
    """
    from .config import SETTINGS
    from .providers.coingecko import CoinGeckoProvider
    from .shadow import ShadowLedger

    settings = settings or SETTINGS
    provider = provider or CoinGeckoProvider()
    ledger = ledger or ShadowLedger(settings.shadow_db)

    fired = 0
    scanned = 0
    for coin in CRYPTO_UNIVERSE:
        if inter_request_sleep:
            import time; time.sleep(inter_request_sleep)  # noqa: E702
        try:
            df = provider.history(coin, days=40)
        except Exception as exc:  # noqa: BLE001
            from .skips import record_skip
            record_skip("crypto_live", coin, exc)
            continue
        if df is None or len(df) < 32 or "close" not in df or "volume" not in df:
            continue
        scanned += 1
        closes = [float(x) for x in df["close"].tolist()]
        vols = [float(x) for x in df["volume"].tolist()]
        r10, r30 = _ranges(closes)
        vol5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else 0.0
        vol20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else 0.0
        read = crypto_mover(range_10d=r10, range_30d=r30,
                            volume_5d=vol5, volume_20d=vol20)
        if not read.coiled_and_loaded:
            continue
        entry = closes[-1]
        # direction-agnostic magnitude bet — recorded as a volatility setup
        ledger.record(
            model="crypto", symbol=coin.upper(), side="MOVE",
            score=read.big_move_prob, expected_move=0.10,
            entry_price=entry, horizon_hours=HORIZON_HOURS,
            payload=f"coiled-spring: {read.note}", gate=True)
        fired += 1
    return (f"crypto: scanned {scanned}, {fired} coiled-and-loaded prediction(s) "
            "recorded (3-day horizon, resolves on the realised move)")


if __name__ == "__main__":
    print(run_crypto_live())
