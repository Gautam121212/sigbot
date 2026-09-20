"""Walk-forward evaluation.

Rules enforced here, not assumed:
  * chronological only — no shuffling, ever
  * the model is refit on [t-train_window, t) and used on [t, t+step)
  * the label for row t is realised at t+1, so the last row of every fit
    window is dropped before training
  * costs are charged on every signal
  * results are compared against two baselines the system must beat
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .daily_model import DailyModel
from .decide import Gates, decide
from .stats import brier_score, expected_calibration_error, log_loss, max_drawdown, wilson_interval


@dataclass
class BacktestResult:
    symbol: str
    n_predictions: int = 0
    n_signals: int = 0
    brier: float = float("nan")
    brier_baseline: float = float("nan")
    logloss: float = float("nan")
    ece: float = float("nan")
    directional_accuracy: float = float("nan")
    base_rate: float = float("nan")
    signal_hit_rate: float = float("nan")
    signal_hit_lower: float = float("nan")
    mean_net_return: float = float("nan")
    total_net_return: float = float("nan")
    max_drawdown: float = float("nan")
    predictions: pd.DataFrame = field(default_factory=pd.DataFrame)

    def summary(self) -> str:
        skill = self.brier_baseline - self.brier
        lines = [
            f"--- {self.symbol} ---",
            f"predictions            {self.n_predictions}",
            f"base rate (up days)    {self.base_rate:.3f}",
            f"directional accuracy   {self.directional_accuracy:.3f}",
            f"Brier                  {self.brier:.4f}   (baseline {self.brier_baseline:.4f}, skill {skill:+.4f})",
            f"log loss               {self.logloss:.4f}",
            f"calibration error ECE  {self.ece:.4f}",
            f"signals fired          {self.n_signals}",
        ]
        if self.n_signals:
            lines += [
                f"signal hit rate        {self.signal_hit_rate:.3f} (90% lower bound {self.signal_hit_lower:.3f})",
                f"mean net return/signal {self.mean_net_return:+.4%}",
                f"total net return       {self.total_net_return:+.2%}",
                f"max drawdown           {self.max_drawdown:.2%}",
            ]
        else:
            lines.append("signal hit rate        n/a — no signal cleared the gates")
        return "\n".join(lines)


def walk_forward(
    dataset: pd.DataFrame,
    symbol: str = "?",
    train_window: int = 750,
    step: int = 21,
    gates: Gates | None = None,
) -> BacktestResult:
    gates = gates or Gates()
    data = dataset.dropna(subset=["y_up", "fwd_ret"]).copy()
    res = BacktestResult(symbol=symbol)
    if len(data) < train_window + step:
        return res

    rows = []
    start = train_window
    while start < len(data):
        stop = min(start + step, len(data))
        train = data.iloc[start - train_window : start]
        test = data.iloc[start:stop]
        try:
            model = DailyModel().fit(train)
        except ValueError:
            start = stop
            continue

        p = model.predict_proba(test)
        for (idx, row), p_up in zip(test.iterrows(), p):
            up_lo, dn_lo, n_bin = model.bin_bounds(float(p_up))
            exp_move, q10, q90 = model.move_stats(float(p_up), float(row["vol_20"]))
            d = decide(float(p_up), up_lo, dn_lo, exp_move, n_bin,
                       model.base_rate, gates, model.oof_skill)
            fwd = float(row["fwd_ret"])
            if d.side == "BUY":
                net = fwd - gates.cost_pct
            elif d.side == "SELL":
                net = -fwd - gates.cost_pct
            else:
                net = 0.0
            rows.append(
                dict(date=idx, p_up=float(p_up), p_up_lower=up_lo, p_dn_lower=dn_lo,
                     bin_n=n_bin, exp_move=exp_move, q10=q10, q90=q90,
                     side=d.side, fwd_ret=fwd, y_up=float(row["y_up"]), net=net)
            )
        start = stop

    if not rows:
        return res

    df = pd.DataFrame(rows).set_index("date")
    res.predictions = df
    p, y = df["p_up"].to_numpy(), df["y_up"].to_numpy()
    res.n_predictions = len(df)
    res.base_rate = float(y.mean())
    res.brier = brier_score(p, y)
    res.brier_baseline = brier_score(np.full_like(p, res.base_rate), y)
    res.logloss = log_loss(p, y)
    res.ece = expected_calibration_error(p, y)
    res.directional_accuracy = float(((p > 0.5).astype(float) == y).mean())

    sig = df[df["side"] != "HOLD"]
    res.n_signals = len(sig)
    if len(sig):
        wins = float((sig["net"] > 0).sum())
        res.signal_hit_rate = wins / len(sig)
        res.signal_hit_lower = wilson_interval(wins, len(sig), 0.90)[0]
        res.mean_net_return = float(sig["net"].mean())
        equity = (1.0 + df["net"]).cumprod().to_numpy()
        res.total_net_return = float(equity[-1] - 1.0)
        res.max_drawdown = max_drawdown(equity)
    return res
