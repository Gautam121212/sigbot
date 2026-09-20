"""Calibration and uncertainty maths.

Everything here is pure. No I/O, no global state. This is the module that
decides whether a number is allowed to look confident.
"""
from __future__ import annotations

import numpy as np

Z = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}


def wilson_interval(successes: float, n: float, conf: float = 0.90) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Returns (lower, upper). With n == 0 returns (0.0, 1.0): maximum ignorance,
    never a fabricated point estimate.
    """
    if n <= 0:
        return 0.0, 1.0
    z = Z.get(round(conf, 2), 1.6449)
    p = successes / n
    den = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    margin = z * np.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return float((centre - margin) / den), float((centre + margin) / den)


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p: np.ndarray, y: np.ndarray, eps: float = 1e-12) -> float:
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability_table(p: np.ndarray, y: np.ndarray, n_bins: int = 10):
    """Return per-bin (lo, hi, n, mean_predicted, observed_freq, wilson_lower)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & (p < hi) if i < n_bins - 1 else (p >= lo) & (p <= hi)
        n = int(m.sum())
        if n == 0:
            rows.append((lo, hi, 0, np.nan, np.nan, np.nan))
            continue
        obs = float(y[m].mean())
        wl, _ = wilson_interval(y[m].sum(), n)
        rows.append((lo, hi, n, float(p[m].mean()), obs, wl))
    return rows


def expected_calibration_error(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    """Sample-weighted mean |predicted - observed| across reliability bins."""
    rows = reliability_table(p, y, n_bins)
    total = sum(r[2] for r in rows)
    if total == 0:
        return float("nan")
    return float(sum(r[2] * abs(r[3] - r[4]) for r in rows if r[2] > 0) / total)


def max_drawdown(equity: np.ndarray) -> float:
    equity = np.asarray(equity, float)
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))
