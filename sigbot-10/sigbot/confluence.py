"""Confluence: combining signals, with the independence assumption checked.

Requiring two signals to agree raises the hit rate — but only in proportion to
how independent they are. For two signals each correct with probability p,
whose correctness is correlated with coefficient rho:

    P(correct | both agree) = [p² + rho·p(1-p)] / [p² + (1-p)² + 2·rho·p(1-p)]

Which gives:

        p     rho    P(correct|agree)   agreement rate
      0.72   0.00              86.9%            59.7%
      0.72   0.30              80.7%            71.8%
      0.72   0.60              76.2%            83.9%
      0.72   0.80              73.9%            91.9%
      0.72   0.95              72.5%            98.0%

At rho = 0.8 the lift is 1.9 points, not 15. And rho is high whenever signals
share inputs: a gap-plus-volume detector, an RSI-plus-volume detector and a
volume-plus-52-week-high detector all key off the same volume spike and the
same price move on the same bar. Treating their agreement as independent
confirmation is double-counting one observation.

So this module does not assume independence. It measures rho from the signals'
own resolved history and reports the lift that measurement supports — which is
often approximately none.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .stats import wilson_interval

MIN_PAIRS_FOR_RHO = 40


def agreement_posterior(p: float, rho: float) -> tuple[float, float]:
    """Return (P(correct | signals agree), P(they agree)) for two signals.

    rho is the correlation between the two signals' correctness indicators,
    clipped to the range where the joint distribution stays valid.
    """
    p = float(np.clip(p, 1e-6, 1 - 1e-6))
    q = 1.0 - p
    rho = float(np.clip(rho, -min(p / q, q / p), 1.0))
    both_right = p * p + rho * p * q
    both_wrong = q * q + rho * p * q
    denom = both_right + both_wrong
    if denom <= 0:
        return p, 0.0
    return float(both_right / denom), float(denom)


def measure_rho(correct_a: list[bool], correct_b: list[bool]) -> float | None:
    """Phi coefficient between two signals' correctness on co-occurring events.

    Returns None when there are too few paired observations to estimate it, and
    the caller must then refuse to claim any confluence lift rather than
    defaulting to the flattering assumption of independence.
    """
    if len(correct_a) != len(correct_b):
        raise ValueError("paired histories must be the same length")
    if len(correct_a) < MIN_PAIRS_FOR_RHO:
        return None
    a = np.asarray(correct_a, float)
    b = np.asarray(correct_b, float)
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


@dataclass(frozen=True)
class Confluence:
    signal_a: str
    signal_b: str
    n_paired: int
    rho: float | None
    base_p: float
    posterior: float | None
    agreement_rate: float | None

    @property
    def lift(self) -> float | None:
        return None if self.posterior is None else self.posterior - self.base_p

    @property
    def claimable(self) -> bool:
        """Confluence may only be claimed on a measured, materially positive lift."""
        return (self.rho is not None and self.lift is not None
                and self.lift >= 0.03 and self.n_paired >= MIN_PAIRS_FOR_RHO)

    def render(self) -> str:
        head = f"{self.signal_a} + {self.signal_b}: {self.n_paired} paired events"
        if self.rho is None:
            return (f"{head}\n  correlation not estimable ({self.n_paired} < "
                    f"{MIN_PAIRS_FOR_RHO} pairs). No confluence lift may be claimed.")
        body = (f"\n  measured correlation rho={self.rho:+.2f}"
                f"\n  single-signal rate {self.base_p:.1%} -> agreement rate "
                f"{self.posterior:.1%} (lift {self.lift:+.1%})"
                f"\n  signals agree on {self.agreement_rate:.0%} of events")
        if not self.claimable:
            body += ("\n  lift is too small to act on — these signals are largely "
                     "the same observation counted twice")
        return head + body


def evaluate_confluence(signal_a: str, signal_b: str,
                        correct_a: list[bool], correct_b: list[bool]) -> Confluence:
    n = min(len(correct_a), len(correct_b))
    rho = measure_rho(correct_a[:n], correct_b[:n])
    base_p = float(np.mean(correct_a[:n] + correct_b[:n])) if n else float("nan")
    if rho is None or not np.isfinite(base_p):
        return Confluence(signal_a, signal_b, n, rho, base_p, None, None)
    post, rate = agreement_posterior(base_p, rho)
    return Confluence(signal_a, signal_b, n, rho, base_p, post, rate)


def observed_agreement_rate(correct_a: list[bool], correct_b: list[bool],
                            side_a: list[str], side_b: list[str],
                            conf: float = 0.90) -> tuple[int, float, float]:
    """Empirical hit rate on events where both signals took the same side.

    Preferred over the analytic posterior whenever there is enough data: it
    needs no distributional assumption and no rho estimate. Returns
    (n_agreeing, hit_rate, wilson_lower).
    """
    agree = [i for i in range(min(len(side_a), len(side_b))) if side_a[i] == side_b[i]]
    if not agree:
        return 0, float("nan"), 0.0
    hits = sum(1 for i in agree if correct_a[i])
    lo, _ = wilson_interval(hits, len(agree), conf)
    return len(agree), hits / len(agree), float(lo)
