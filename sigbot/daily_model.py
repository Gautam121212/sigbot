"""Model B — the watchlist forecaster.

Predicts P(next daily close > today's close) for a fixed universe, calibrates
it against a chronologically held-out slice, and attaches a reliability-bin
lower bound so that a thin or badly-calibrated region of probability space
cannot produce a confident-looking signal.

Deliberately boring: regularised logistic regression on ~16 features.
A boosted tree on 16 features and 750 daily rows overfits and produces
probabilities that look sharp and are wrong. If you want to try one anyway,
swap `_make_estimator` and re-run the backtest before believing anything.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURE_COLUMNS
from .stats import wilson_interval

N_BINS = 10
N_OOF_BLOCKS = 4
OOF_WARMUP_FRAC = 0.40


def _make_estimator() -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(C=0.05, max_iter=2000, solver="lbfgs")),
        ]
    )


@dataclass
class MoveDistribution:
    """Empirical next-day return distribution, conditioned on volatility tercile."""

    vol_edges: tuple[float, float]
    up_mean: tuple[float, float, float]
    dn_mean: tuple[float, float, float]
    q10: tuple[float, float, float]
    q90: tuple[float, float, float]

    def bucket(self, vol: float) -> int:
        if not np.isfinite(vol):
            return 1
        if vol <= self.vol_edges[0]:
            return 0
        if vol <= self.vol_edges[1]:
            return 1
        return 2


class DailyModel:
    """Fit on a contiguous past window; predict forward. Never refit on test data.

    Calibration is done on pooled out-of-fold predictions from expanding
    chronological blocks, not on a single tail slice. A single tail slice gives
    the isotonic layer ~150 rows, which is enough to manufacture a confident
    reliability bin out of noise — the null test caught exactly that.
    """

    def __init__(self, min_train: int = 400, conf: float = 0.90):
        self.min_train = min_train
        self.conf = conf
        self.pipe: Pipeline | None = None
        self.iso: IsotonicRegression | None = None
        self.bins: list[tuple[float, float, int, float]] = []
        self.moves: MoveDistribution | None = None
        self.base_rate: float = float("nan")
        self.oof_skill: float = float("nan")   # Brier skill vs base rate, out-of-fold
        self.oof_n: int = 0
        self.features: list[str] = list(FEATURE_COLUMNS)
        self.dropped_features: list[str] = []

    # ------------------------------------------------------------------ fit
    def fit(self, train: pd.DataFrame) -> "DailyModel":
        train = train.dropna(subset=["y_up", "fwd_ret"])
        n = len(train)
        if n < self.min_train:
            raise ValueError(f"need >= {self.min_train} training rows, got {n}")

        # Drop features with no observed value in this window. A newly listed
        # asset has fewer than 252 bars, so the 200- and 252-day features are
        # entirely NaN and sklearn warns once per fit. Dropping them here is the
        # same outcome without the noise, and it records which were unusable.
        frame = train[FEATURE_COLUMNS]
        usable = [c for c in FEATURE_COLUMNS if frame[c].notna().any()]
        self.features = usable
        self.dropped_features = [c for c in FEATURE_COLUMNS if c not in usable]
        if len(usable) < 6:
            raise ValueError(
                f"only {len(usable)} of {len(FEATURE_COLUMNS)} features have any "
                "data in this window — too little history to model")
        X = frame[usable].to_numpy(float)
        y = train["y_up"].to_numpy(float)

        edges = np.linspace(int(n * OOF_WARMUP_FRAC), n, N_OOF_BLOCKS + 1).astype(int)
        oof_raw, oof_y = [], []
        for i in range(N_OOF_BLOCKS):
            a, b = int(edges[i]), int(edges[i + 1])
            if b - a < 20 or a < 100:
                continue
            fold = _make_estimator().fit(X[:a], y[:a])
            oof_raw.append(fold.predict_proba(X[a:b])[:, 1])
            oof_y.append(y[a:b])
        if not oof_raw:
            raise ValueError("training window too short for out-of-fold calibration")

        raw = np.concatenate(oof_raw)
        y_oof = np.concatenate(oof_y)
        self.oof_n = int(y_oof.size)

        self.iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw, y_oof)
        p_oof = np.clip(self.iso.predict(raw), 0.0, 1.0)

        self._fit_bins(p_oof, y_oof)
        self.base_rate = float(y.mean())
        base_p = np.full_like(p_oof, float(y_oof.mean()))
        self.oof_skill = float(np.mean((base_p - y_oof) ** 2) - np.mean((p_oof - y_oof) ** 2))

        # Final estimator sees the whole window; the calibrator stays as fitted.
        self.pipe = _make_estimator().fit(X, y)
        self._fit_moves(train)
        return self

    def _fit_bins(self, p: np.ndarray, y: np.ndarray) -> None:
        edges = np.linspace(0.0, 1.0, N_BINS + 1)
        self.bins = []
        for i in range(N_BINS):
            lo, hi = float(edges[i]), float(edges[i + 1])
            m = (p >= lo) & (p < hi) if i < N_BINS - 1 else (p >= lo) & (p <= hi)
            n = int(m.sum())
            hits = float(y[m].sum()) if n else 0.0
            self.bins.append((lo, hi, n, hits))

    def _fit_moves(self, train: pd.DataFrame) -> None:
        vol = train["vol_20"].to_numpy(float)
        fwd = train["fwd_ret"].to_numpy(float)
        ok = np.isfinite(vol) & np.isfinite(fwd)
        vol, fwd = vol[ok], fwd[ok]
        e1, e2 = (np.quantile(vol, [1 / 3, 2 / 3]) if vol.size else (0.0, 0.0))

        ups, dns, q10s, q90s = [], [], [], []
        for lo, hi in ((-np.inf, e1), (e1, e2), (e2, np.inf)):
            m = (vol > lo) & (vol <= hi)
            seg = fwd[m] if m.sum() >= 30 else fwd
            pos, neg = seg[seg > 0], seg[seg <= 0]
            ups.append(float(pos.mean()) if pos.size else 0.0)
            dns.append(float(neg.mean()) if neg.size else 0.0)
            q10s.append(float(np.quantile(seg, 0.10)) if seg.size else 0.0)
            q90s.append(float(np.quantile(seg, 0.90)) if seg.size else 0.0)

        self.moves = MoveDistribution(
            (float(e1), float(e2)), tuple(ups), tuple(dns), tuple(q10s), tuple(q90s)  # type: ignore[arg-type]
        )

    # -------------------------------------------------------------- predict
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.pipe is None or self.iso is None:
            raise RuntimeError("model not fitted")
        raw = self.pipe.predict_proba(X[self.features].to_numpy(float))[:, 1]
        return np.clip(self.iso.predict(raw), 0.0, 1.0)

    def bin_bounds(self, p: float) -> tuple[float, float, int]:
        """Wilson lower bounds for P(up) and P(down) from the calibration bin.

        A probability landing in a bin the calibration set barely populated
        gets a near-zero lower bound. That is the point.
        """
        for lo, hi, n, hits in self.bins:
            inside = lo <= p < hi or (hi >= 1.0 and p >= lo)
            if inside:
                if n == 0:
                    return 0.0, 0.0, 0
                up_lo, _ = wilson_interval(hits, n, self.conf)
                dn_lo, _ = wilson_interval(n - hits, n, self.conf)
                return float(up_lo), float(dn_lo), n
        return 0.0, 0.0, 0

    def move_stats(self, p_up: float, vol: float) -> tuple[float, float, float]:
        if self.moves is None:
            raise RuntimeError("model not fitted")
        b = self.moves.bucket(vol)
        exp_move = p_up * self.moves.up_mean[b] + (1.0 - p_up) * self.moves.dn_mean[b]
        return float(exp_move), float(self.moves.q10[b]), float(self.moves.q90[b])
