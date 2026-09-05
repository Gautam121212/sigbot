"""Model C — contagion network.

The idea: instead of predicting an asset from its own history (hard), predict
a *dependent* asset from a large move in an *anchor* it reacts to. Conditional
prediction is a genuinely easier problem than unconditional prediction, which
is why this is the most promising of the three models.

Two things must be true for it to be tradeable, and they are measured
separately here because conflating them is the standard way this idea fails:

  contemporaneous beta  — dependent moves the SAME day as the anchor.
                          Large, obvious, and worth nothing: by the time you
                          see the anchor move, the dependent has already moved.
  lagged beta           — dependent moves the day AFTER the anchor.
                          This is the only one you can act on.

For liquid US large caps at daily frequency the lagged term is usually
indistinguishable from zero. The screener is built to say so rather than to
find something.

Multiple testing is the other standard failure. Screening 20 anchors against
60 candidates is 1,200 hypotheses; at p<0.05 you get ~60 false discoveries by
luck alone. Benjamini-Hochberg FDR control is applied to every screen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .stats import wilson_interval


# --------------------------------------------------------------------- stats

def _normal_two_sided_p(t: float) -> float:
    """Two-sided p-value from a t-statistic via the normal approximation.

    Valid because every screen here runs on >1,000 daily observations. Avoids
    a scipy dependency for one function.
    """
    if not np.isfinite(t):
        return 1.0
    return float(math.erfc(abs(t) / math.sqrt(2.0)))


def ols_hc1(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, int]:
    """Simple regression y = a + b·x with HC1 heteroskedasticity-robust SE.

    Returns (beta, robust_se, t_stat, n). Financial returns are strongly
    heteroskedastic; classical SEs would overstate significance, which is
    exactly the error this module exists to avoid.
    """
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = x.size
    if n < 60:
        return float("nan"), float("nan"), float("nan"), n

    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta_vec = XtX_inv @ (X.T @ y)
    resid = y - X @ beta_vec
    meat = (X * (resid**2)[:, None]).T @ X
    cov = XtX_inv @ meat @ XtX_inv * (n / max(n - 2, 1))  # HC1 correction
    se = float(np.sqrt(max(cov[1, 1], 0.0)))
    beta = float(beta_vec[1])
    return beta, se, (beta / se if se > 0 else float("nan")), n


def benjamini_hochberg(pvals: list[float], alpha: float = 0.10) -> list[float]:
    """Return BH-adjusted q-values, same order as input."""
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    ranked = np.asarray(pvals, float)[order]
    q = ranked * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]  # enforce monotonicity
    out = np.empty(m)
    out[order] = np.clip(q, 0.0, 1.0)
    return out.tolist()


# --------------------------------------------------------------------- model

@dataclass(frozen=True)
class Link:
    anchor: str
    dependent: str
    beta_contemp: float
    beta_lagged: float
    t_lagged: float
    p_lagged: float
    q_lagged: float
    n_obs: int
    interval: str = "1d"

    @property
    def tradeable(self) -> bool:
        return np.isfinite(self.q_lagged) and self.q_lagged <= 0.10

    def describe(self) -> str:
        unit = "same-bar" if self.interval != "1d" else "same-day"
        nxt = "next-bar" if self.interval != "1d" else "next-day"
        return (
            f"{self.dependent} ~ {self.anchor} [{self.interval}]: "
            f"{unit} beta {self.beta_contemp:+.2f}, "
            f"{nxt} beta {self.beta_lagged:+.3f} "
            f"(t={self.t_lagged:+.2f}, q={self.q_lagged:.3f}, n={self.n_obs})"
        )


@dataclass(frozen=True)
class Response:
    """Event-study response of one dependent to a shock in one anchor."""

    anchor: str
    dependent: str
    sigma_threshold: float
    n_events: int
    mean_response: float      # sign-aligned next-day return of the dependent
    median_response: float
    q10: float
    q90: float
    hit_rate: float           # dependent moved the same way as the anchor shock
    hit_lower: float
    base_hit_rate: float      # unconditional, for comparison

    def describe(self) -> str:
        return (
            f"{self.dependent} after a {self.sigma_threshold:g}σ {self.anchor} move: "
            f"next-day {self.mean_response:+.2%} (10–90% {self.q10:+.2%} to {self.q90:+.2%}), "
            f"direction {self.hit_rate:.0%} vs base {self.base_hit_rate:.0%}, "
            f"n={self.n_events}"
        )


def _aligned_returns(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    return df["a"], df["b"]


def screen_link(anchor: pd.Series, dependent: pd.Series, name_a: str, name_b: str,
                interval: str = "1d") -> Link:
    """Fit contemporaneous and next-bar response of `dependent` to `anchor`."""
    a, b = _aligned_returns(anchor, dependent)
    beta_c, _, _, _ = ols_hc1(a.to_numpy(float), b.to_numpy(float))
    # dependent at t+1 regressed on anchor at t
    beta_l, _, t_l, n = ols_hc1(a.to_numpy(float)[:-1], b.to_numpy(float)[1:])
    return Link(name_a, name_b, beta_c, beta_l, t_l, _normal_two_sided_p(t_l),
                float("nan"), n, interval)


def build_network(
    returns: dict[str, pd.Series],
    anchors: list[str],
    candidates: list[str],
    alpha: float = 0.10,
    interval: str = "1d",
) -> list[Link]:
    """Screen every anchor × candidate pair, then apply BH-FDR across all of them.

    FDR is applied to the whole screen, not per anchor. Correcting per anchor
    would let the total false-discovery count scale with the number of anchors,
    which is the mistake this is meant to prevent.
    """
    links: list[Link] = []
    for a_name in anchors:
        if a_name not in returns:
            continue
        for d_name in candidates:
            if d_name == a_name or d_name not in returns:
                continue
            link = screen_link(returns[a_name], returns[d_name], a_name, d_name, interval)
            if np.isfinite(link.t_lagged):
                links.append(link)

    qs = benjamini_hochberg([lk.p_lagged for lk in links], alpha)
    return [
        Link(lk.anchor, lk.dependent, lk.beta_contemp, lk.beta_lagged,
             lk.t_lagged, lk.p_lagged, q, lk.n_obs, lk.interval)
        for lk, q in zip(links, qs)
    ]


def event_response(
    anchor: pd.Series,
    dependent: pd.Series,
    name_a: str,
    name_b: str,
    sigma: float = 2.0,
    vol_window: int = 60,
) -> Response | None:
    """Distribution of the dependent's next-day return after an anchor shock.

    Shock threshold is |z| >= sigma using a TRAILING volatility estimate, so
    the definition of "large move" only uses information available that day.
    Up- and down-shocks are pooled by sign-aligning the dependent's response.
    """
    a, b = _aligned_returns(anchor, dependent)
    if len(a) < vol_window + 200:
        return None

    vol = a.rolling(vol_window).std().shift(1)  # shift: no same-day vol leak
    z = a / vol
    shock = z.abs() >= sigma

    nxt = b.shift(-1)
    aligned = (nxt * np.sign(a))[shock].dropna()
    if aligned.size < 10:
        return None

    base = (b.shift(-1) * np.sign(a)).dropna()
    hits = float((aligned > 0).sum())
    lo, _ = wilson_interval(hits, aligned.size, 0.90)

    return Response(
        anchor=name_a,
        dependent=name_b,
        sigma_threshold=sigma,
        n_events=int(aligned.size),
        mean_response=float(aligned.mean()),
        median_response=float(aligned.median()),
        q10=float(np.quantile(aligned, 0.10)),
        q90=float(np.quantile(aligned, 0.90)),
        hit_rate=hits / aligned.size,
        hit_lower=float(lo),
        base_hit_rate=float((base > 0).mean()),
    )


@dataclass(frozen=True)
class ContagionGates:
    min_events: int = 40          # 2σ shocks are rare: 10 years gives ~50
    min_hit_lower: float = 0.58
    min_edge_over_base: float = 0.03
    cost_pct: float = 0.0015
    max_q: float = 0.10


def gate(resp: Response, link: Link, gates: ContagionGates) -> tuple[bool, list[str]]:
    """Return (may_alert, blocking_reasons)."""
    blocked: list[str] = []
    if not link.tradeable:
        blocked.append(f"lagged link not significant after FDR (q={link.q_lagged:.3f})")
    if resp.n_events < gates.min_events:
        blocked.append(f"only {resp.n_events} historical shocks (need {gates.min_events})")
    if resp.hit_lower < gates.min_hit_lower:
        blocked.append(
            f"direction lower bound {resp.hit_lower:.0%} < {gates.min_hit_lower:.0%}"
        )
    if resp.hit_rate - resp.base_hit_rate < gates.min_edge_over_base:
        blocked.append(
            f"edge over base {resp.hit_rate - resp.base_hit_rate:+.1%} "
            f"< {gates.min_edge_over_base:.0%}"
        )
    if abs(resp.mean_response) <= gates.cost_pct:
        blocked.append(f"mean response {resp.mean_response:+.2%} inside costs")
    return (not blocked), blocked
