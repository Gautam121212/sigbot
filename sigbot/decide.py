"""The one place a BUY/SELL/HOLD is decided.

Backtest and live runner both call this. If they diverged, the backtest would
be measuring a system you do not ship. Do not inline this logic anywhere else.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Gates:
    prob_threshold: float = 0.60   # applied to the LOWER BOUND, not the point estimate
    min_bin_n: int = 40            # calibration-bin support required
    cost_pct: float = 0.0010       # 10 bps round trip; raise for crypto/small caps
    min_edge_over_base: float = 0.02
    min_model_skill: float = 0.002  # out-of-fold Brier skill the model must show
                                    # before ANY of its predictions may trade


@dataclass(frozen=True)
class Decision:
    side: str
    reasons: list[str]
    blocked_by: list[str]


def decide(
    p_up: float,
    p_up_lower: float,
    p_dn_lower: float,
    expected_move: float,
    bin_n: int,
    base_rate: float,
    gates: Gates,
    model_skill: float = float("nan"),
) -> Decision:
    reasons: list[str] = []
    blocked: list[str] = []

    # Model-level gate first. A model with no demonstrated out-of-fold skill
    # has nothing to say, however extreme any individual probability looks.
    if not (model_skill > gates.min_model_skill):
        blocked.append(
            f"model shows no out-of-fold skill (Brier skill {model_skill:+.4f} "
            f"<= {gates.min_model_skill:+.4f})"
        )

    if bin_n < gates.min_bin_n:
        blocked.append(f"calibration support {bin_n} < {gates.min_bin_n}")

    long_ok = (
        p_up_lower >= gates.prob_threshold
        and expected_move - gates.cost_pct > 0
        and p_up >= base_rate + gates.min_edge_over_base
    )
    short_ok = (
        p_dn_lower >= gates.prob_threshold
        and -expected_move - gates.cost_pct > 0
        and (1.0 - p_up) >= (1.0 - base_rate) + gates.min_edge_over_base
    )

    if blocked:
        return Decision("HOLD", reasons, blocked)

    if long_ok and not short_ok:
        reasons = [
            f"P(up) lower bound {p_up_lower:.1%} >= {gates.prob_threshold:.0%}",
            f"expected move {expected_move:+.2%} clears {gates.cost_pct:.2%} costs",
            f"base rate here is {base_rate:.1%}",
        ]
        return Decision("BUY", reasons, blocked)

    if short_ok and not long_ok:
        reasons = [
            f"P(down) lower bound {p_dn_lower:.1%} >= {gates.prob_threshold:.0%}",
            f"expected move {expected_move:+.2%} clears {gates.cost_pct:.2%} costs",
            f"base rate here is {base_rate:.1%}",
        ]
        return Decision("SELL", reasons, blocked)

    if p_up_lower < gates.prob_threshold and p_dn_lower < gates.prob_threshold:
        blocked.append(
            f"neither direction clears threshold (up {p_up_lower:.1%}, down {p_dn_lower:.1%})"
        )
    if abs(expected_move) <= gates.cost_pct:
        blocked.append(f"expected move {expected_move:+.2%} inside costs")
    return Decision("HOLD", reasons, blocked)
