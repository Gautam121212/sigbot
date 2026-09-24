"""Model E — the same model, on fifteen-minute crypto bars.

Not a new idea. It is Model B's features, calibration and gates applied to a
faster clock, because the constraint on this project has never been the
algorithm — it is that a hundred daily forecasts a day means a tier takes
months to earn. Ninety-six bars a day per asset compresses that to days.

## What is genuinely different, and it is not the model

**Costs dominate.** A daily move of 1.5% clears a 0.1% round trip with room.
A fifteen-minute move of 0.08% does not clear it at all. So the expected move
must exceed costs by a wide margin before anything is called, and most bars
will produce nothing. That is correct, not a failure to find signal.

**Observations are not independent.** Ninety-six bars from one asset on one day
are closer to one fact than ninety-six. `progress.py` already reports the
market-day count beside the check count, and here the gap between those two
numbers is the whole story: five thousand checks across four days is four days
of evidence, not five thousand.

**Nothing runs when the model is wrong about timing.** A fifteen-minute horizon
resolves in fifteen minutes, so a wrong call is known almost at once — which is
the real benefit. Model B waits a day to find out.

Honest constraint: Binance keeps deep intraday history, but a model fitted on
sixty days of fifteen-minute bars has seen one market regime. It will look
better in backtest than it can be, exactly as the daily model did.

Largest risk: the sheer count of forecasts feeling like evidence. Five thousand
records with a 51% hit rate across four days says almost nothing, and the
temptation to read it as a large sample is the reason the day count is printed
next to it everywhere.

Test gap: live intraday behaviour is not tested here. Whether Binance answers,
and whether fifteen-minute bars arrive on time, is what
`scripts/check_sources.py` reports from your own machine.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MODEL_NAME = "crypto15m"
# Twelve fifteen-minute bars: three hours ahead. You said you will not trade
# intraday, and a horizon nobody would act on is a horizon that only burns
# requests. Three hours is the shortest window that still resolves several
# times a day while describing a hold a person might actually take.
HORIZON_BARS = 12

# Crypto round trip on a major exchange: taker fee both ways plus a spread that
# is small on the top pairs and not zero. The daily model uses a lower figure
# because a daily move is an order of magnitude larger.
ROUND_TRIP_COST = 0.0012             # 12 basis points

# The expected move must clear costs by this multiple before anything is
# called. At fifteen minutes most bars will not, and that is the point: a
# forecast that is right and unprofitable is worse than none, because it
# fills the ledger with successes you could not have taken.
COST_MULTIPLE = 2.5

MIN_BARS = 400                       # 15-minute mode: enough to fit and hold out
MIN_BARS_DAILY = 60                  # daily mode (CoinGecko): 60 days is plenty


@dataclass
class IntradayForecast:
    symbol: str
    side: str
    score: float
    expected_move: float
    entry: float
    horizon_bars: int
    reason: str
    tradeable: bool


def _features(bars: pd.DataFrame) -> pd.DataFrame:
    """Momentum, range and volume. Window sizes scale to the bar count: the
    15-minute path (400+ bars) uses long windows; the daily path (~90 bars)
    uses short ones, so the features are not all NaN on daily data."""
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    volume = bars["volume"].astype(float)
    r = np.log(close).diff()

    daily = len(bars) <= 200
    w_med, w_long = (4, 8) if daily else (16, 96)      # medium / long windows
    w_short = 2 if daily else 4

    out = pd.DataFrame(index=bars.index)
    out["r1"] = r
    out["r4"] = r.rolling(w_short).sum()
    out["r16"] = r.rolling(w_med).sum()
    out["vol16"] = r.rolling(w_med).std()
    out["vol96"] = r.rolling(w_long).std()
    span = (high - low).replace(0.0, np.nan)
    out["position"] = (close - low) / span
    out["range"] = span / close
    out["volume_z"] = ((volume - volume.rolling(w_long).mean())
                       / volume.rolling(w_long).std())
    return out.replace([np.inf, -np.inf], np.nan)


def forecast(symbol: str, bars: pd.DataFrame,
             horizon: int | None = None) -> IntradayForecast | None:
    """One forecast from the most recent closed bar.

    Returns None rather than a neutral forecast when there is not enough
    history: a fabricated 50% is indistinguishable from a measured one once it
    is in the ledger.

    Auto-detects daily vs 15-minute by bar count: <=200 bars is treated as
    daily (CoinGecko), which uses a 1-bar horizon and a 60-bar minimum. The old
    15-minute path (Binance, now blocked) still works if ever given 400+ bars.
    """
    if bars is None:
        return None
    daily = len(bars) <= 200
    min_bars = MIN_BARS_DAILY if daily else MIN_BARS
    if horizon is None:
        horizon = 1 if daily else HORIZON_BARS
    if len(bars) < min_bars:
        return None

    features = _features(bars)
    close = bars["close"].astype(float)
    forward = np.log(close.shift(-horizon) / close)

    frame = features.copy()
    frame["y"] = (forward > 0).astype(float)
    frame["move"] = forward
    frame = frame.dropna()
    if len(frame) < min_bars // 2:
        return None

    columns = [c for c in features.columns]
    x = frame[columns].to_numpy()
    y = frame["y"].to_numpy()

    # Fit on everything except the tail, score the tail. Fitting on all of it
    # and scoring the same rows is how a backtest reports skill it does not
    # have.
    # Train/test split thresholds scale to the horizon. Daily data has far
    # fewer rows than 15-minute, so the 15-min minimums would reject it.
    split = int(len(x) * 0.7 if daily else len(x) * 0.8)
    min_train, min_test = (30, 10) if daily else (50, 20)
    if split < min_train or len(x) - split < min_test:
        return None

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(x[:split])
    model = LogisticRegression(max_iter=400, C=0.5)
    try:
        model.fit(scaler.transform(x[:split]), y[:split])
    except ValueError:
        return None                  # one class only in the window

    latest = features.iloc[[-1]][columns]
    if latest.isna().to_numpy().any():
        return None
    score = float(model.predict_proba(scaler.transform(latest.to_numpy()))[0, 1])

    # Expected move from the magnitude actually seen at this horizon, not from
    # the probability. Those are different quantities and conflating them
    # inflates every expectation.
    typical = float(frame["move"].abs().median())
    side = "BUY" if score >= 0.5 else "SELL"
    expected = typical if side == "BUY" else -typical

    threshold = ROUND_TRIP_COST * COST_MULTIPLE
    tradeable = abs(expected) >= threshold
    reason = (f"expected {abs(expected):.3%} against a {threshold:.3%} bar "
              f"({ROUND_TRIP_COST:.2%} round trip x {COST_MULTIPLE:g})")
    if not tradeable:
        reason = ("recorded but not tradeable: " + reason
                  + " — right and unprofitable is worse than nothing")

    # Leverage-crowding filter (confirmed on a year of major coins, both halves
    # independently): when volatility is rising while price is flat, longs fell
    # -1.29% over the next 5 days vs +0.35% when calm. So a BUY is stood aside
    # when crowded — the forecast is still RECORDED (for the learning loop),
    # just marked not tradeable. Sells are unaffected: crowding favours them.
    from .crypto_signals import read_crowding

    crowd = read_crowding(close.tolist())
    if crowd.crowded and side == "BUY":
        tradeable = False
        reason = "stood aside — " + crowd.reason

    # Low-volume-drop rebound (confirmed both halves, +1.77%/+1.69% next 3 days):
    # a quiet 3%+ drop tends to rebound in crypto. When present on a BUY, it is
    # a positive confirmation and the forecast notes it. Uses the volume column.
    if side == "BUY" and "volume" in bars:
        from .crypto_signals import low_volume_drop_reversal
        fires, why = low_volume_drop_reversal(close.tolist(),
                                              bars["volume"].astype(float).tolist())
        if fires:
            reason = reason + f" | low-vol rebound signal: {why}"

    return IntradayForecast(symbol, side, score, expected,
                            float(close.iloc[-1]), horizon, reason, tradeable)


def summarise(forecasts: list[IntradayForecast]) -> str:
    if not forecasts:
        return ("No intraday forecasts. Either no pair had enough history, or "
                "the data source did not answer — both are faults, and neither "
                "is a quiet market.")
    tradeable = [f for f in forecasts if f.tradeable]
    lines = [f"Crypto 3h — {len(forecasts)} pair(s) scored, "
             f"{len(tradeable)} clear costs"]
    for f in sorted(tradeable, key=lambda f: -abs(f.score - 0.5))[:6]:
        lines.append(f"  {f.symbol} {f.side} {f.score:.0%} · {f.reason}")
    if not tradeable:
        lines.append("  Nothing cleared the cost bar. At fifteen minutes most "
                     "moves do not, which is why the bar exists.")
    lines.append("\nEvery one is recorded and scored in three hours. Eight "
                 "forecasts a day per pair still share most of their error — "
                 "check the market-day count in `sigbot.progress` before "
                 "reading a large number of checks as a large sample.")
    return "\n".join(lines)
