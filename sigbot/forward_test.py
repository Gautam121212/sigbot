"""Forward-test harness — the discipline that separates real edges from mirages.

The deep lesson of this project: REVERSE-ENGINEERING (what preceded the winners)
finds patterns that are survivorship bias, and they FAIL when tested forward.
The only honest test is: measure a signal AT TIME T, then the return AFTER T,
across ALL cases — not just the winners.

Two edges died this way this session:
  - crypto turnover: snapshot +26%, forward -3.8% (reverse-causation)
  - crypto deep-drawdown: looked huge on Fantom-style winners, forward -4.0%
    (survivorship — only the recovered ones were visible)

This harness makes forward-testing the default. A signal is only adopted if its
FORWARD return (signal at T -> return over the next N periods) beats the base
rate out-of-sample. It reads banked time series and refuses to grade a signal
on the same window that defined it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForwardResult:
    signal: str
    n: int
    mean_forward: float        # mean return AFTER the signal fired
    baseline: float            # mean forward return of all cases
    edge: float                # mean_forward - baseline
    survives: bool
    note: str


def forward_test(name: str, fired: list[float], baseline_all: list[float],
                 min_n: int = 50) -> ForwardResult:
    """Grade a signal by its FORWARD returns.

    fired: forward returns of cases where the signal fired (measured at T,
           return realised AFTER T).
    baseline_all: forward returns of ALL cases (the base rate).
    A signal survives only if it has enough cases AND beats the baseline forward.
    """
    if len(fired) < min_n:
        return ForwardResult(name, len(fired), 0.0, 0.0, 0.0, False,
                             f"only {len(fired)} cases — too few to trust")
    mf = sum(fired) / len(fired)
    base = sum(baseline_all) / len(baseline_all) if baseline_all else 0.0
    edge = mf - base
    survives = edge > 0.5      # must beat the base rate by a real margin (0.5%)
    return ForwardResult(
        name, len(fired), round(mf, 2), round(base, 2), round(edge, 2), survives,
        (f"forward {mf:+.1f}% vs baseline {base:+.1f}% (edge {edge:+.1f}%) — "
         + ("SURVIVES" if survives else "FAILS forward, do not ship")))


# The forward verdicts recorded this session (crypto, free price data).
CRYPTO_FORWARD_VERDICTS = {
    "turnover (high vol/mcap)": "-3.8% forward vs -1.9% baseline — FAILS "
                                "(snapshot +26% was reverse-causation)",
    "deep-drawdown survivor": "-4.0% forward vs -2.8% baseline — FAILS "
                              "(survivorship: only recovered coins were visible)",
    "near-highs momentum": "+2.2% forward — weak, regime-swamped, not exceptional",
}


def describe() -> str:
    lines = ["FORWARD-TEST verdicts (crypto, free price data)", ""]
    for sig, verdict in CRYPTO_FORWARD_VERDICTS.items():
        lines.append(f"  {sig}: {verdict}")
    lines.append("")
    lines.append("LESSON: reverse-engineered patterns are survivorship bias;")
    lines.append("forward-testing kills most of them. Crypto's free-price edges")
    lines.append("do not survive forward — the real edge needs on-chain/alt-data.")
    return "\n".join(lines)
