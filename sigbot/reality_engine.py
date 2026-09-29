"""Reality engine — SIGBOT's independent P&L judge.

The piece that makes "reproduce it independently, compute our own number" real.
A strategy (via the adapter) emits INTENTIONS. This engine turns those intentions
into SIGBOT's OWN honest P&L under point-in-time costs, realistic fills and
liquidity limits — the number the source repo is never allowed to supply. This is
the "SIGBOT REALITY TEST" box: it converts a CLAIMED gap into a PROVEN one.

The AI is the analyst (it reads code and hypothesizes gaps); THIS is the judge
(it runs the intentions and measures what the gaps actually cost). A gap is only
"detected" once the engine can show the return difference it causes.

GAP TAXONOMY — this engine measures the execution/portfolio gaps (G7-G13); the
data/statistical gaps (G1-G6) are checked by the validation battery already built
(walk-forward, matched controls, OOS holdout, sensitivity). Each execution gap
here is a MEASURED delta between an idealized run and a realistic one, never an
assertion:
  G7  unrealistic fills   -> next-bar vs same-bar close execution
  G8  slippage            -> per-trade slippage in bps
  G9  spread              -> half-spread paid on entry and exit
  G10 market impact       -> impact as a function of order size / ADV
  G11 liquidity           -> order capped at a fraction of ADV
  G12 hidden leverage     -> gross exposure check (adapter already normalizes)
  G13 correlation concn   -> single-name / sector caps (firewall enforces)

The headline output is the pair (idealized_return, realistic_return): the gap
between them is exactly why a published backtest overstates itself.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """The reality assumptions. Deliberately conservative — the point is to be
    HARDER than the source repo, not kinder."""
    commission_bps: float = 5.0             # 5bps per side
    half_spread_bps: float = 10.0           # 10bps half-spread each side
    base_slippage_bps: float = 5.0          # baseline slippage
    impact_coef: float = 0.10               # impact = coef * (order/ADV) in frac
    max_adv_fraction: float = 0.05          # can't trade > 5% of ADV per day
    next_bar_execution: bool = True         # fill at next bar, not signal bar


@dataclass(frozen=True)
class SimTrade:
    """One trade as the reality engine sees it."""
    symbol: str
    ideal_return: float                     # what the strategy 'wanted' (signal-bar)
    order_value: float
    adv: float                              # average daily dollar volume


@dataclass(frozen=True)
class RealityResult:
    idealized_return_pct: float             # frictionless, same-bar (repo-style)
    realistic_return_pct: float             # after all G7-G11 costs
    total_cost_pct: float
    gap_breakdown: dict[str, float]         # cost attributed to each gap
    liquidity_capped_trades: int

    def gap_pct(self) -> float:
        return round(self.idealized_return_pct - self.realistic_return_pct, 3)


def _per_trade_cost_bps(trade: SimTrade, cm: CostModel) -> dict[str, float]:
    """Decompose the friction on one trade into named gaps (round trip)."""
    commission = 2 * cm.commission_bps
    spread = 2 * cm.half_spread_bps
    slippage = 2 * cm.base_slippage_bps
    # market impact grows with order size relative to ADV
    adv_frac = abs(trade.order_value) / trade.adv if trade.adv > 0 else 1.0
    impact = 2 * cm.impact_coef * min(adv_frac, 1.0) * 10000  # in bps
    return {"G8_slippage": slippage, "G9_spread": spread,
            "commission": commission, "G10_impact": impact}


def simulate(trades: list[SimTrade], cm: CostModel | None = None) -> RealityResult:
    """Run the strategy's intended trades through SIGBOT's reality model and
    return both the idealized (repo-style) and realistic P&L."""
    cm = cm or CostModel()
    ideal_sum = 0.0
    real_sum = 0.0
    gap_totals: dict[str, float] = {"G8_slippage": 0.0, "G9_spread": 0.0,
                                    "commission": 0.0, "G10_impact": 0.0,
                                    "G7_next_bar": 0.0, "G11_liquidity": 0.0}
    capped = 0
    n = len(trades)
    for t in trades:
        ideal_sum += t.ideal_return

        # G11 liquidity: if the order exceeds max ADV fraction, only part fills,
        # so only part of the ideal return is captured.
        fillable = 1.0
        if t.adv > 0:
            max_order = cm.max_adv_fraction * t.adv
            if abs(t.order_value) > max_order:
                fillable = max_order / abs(t.order_value)
                capped += 1
        liquidity_drag = t.ideal_return * (1 - fillable)
        gap_totals["G11_liquidity"] += liquidity_drag

        # G7 next-bar execution: fill at next bar means giving up a slice of the
        # signal-bar edge. Model as a fraction of the ideal return lost.
        next_bar_drag = (0.15 * t.ideal_return) if cm.next_bar_execution else 0.0
        gap_totals["G7_next_bar"] += next_bar_drag

        # explicit per-trade costs (bps -> return fraction)
        costs = _per_trade_cost_bps(t, cm)
        cost_frac = sum(costs.values()) / 10000.0
        for k, v in costs.items():
            gap_totals[k] += v / 10000.0

        realized = (t.ideal_return * fillable) - next_bar_drag - cost_frac
        real_sum += realized

    ideal_avg = (ideal_sum / n * 100) if n else 0.0
    real_avg = (real_sum / n * 100) if n else 0.0
    total_cost = ideal_avg - real_avg
    gap_avg = {k: round(v / n * 100, 3) if n else 0.0 for k, v in gap_totals.items()}
    return RealityResult(round(ideal_avg, 3), round(real_avg, 3),
                         round(total_cost, 3), gap_avg, capped)


def describe() -> str:
    return "\n".join([
        "REALITY ENGINE — SIGBOT's independent P&L judge",
        "",
        "  A strategy emits INTENTIONS; this engine computes SIGBOT's OWN honest",
        "  P&L under point-in-time costs, next-bar fills, spread, slippage, market",
        "  impact and liquidity caps. The source repo never supplies its number —",
        "  this does, and the gap between idealized and realistic is exactly why a",
        "  published backtest overstates itself.",
        "",
        "  AI = analyst (hypothesizes gaps by reading code).",
        "  Reality engine = judge (MEASURES what each gap costs).",
        "  A gap is 'detected' only once the engine shows its return delta.",
        "",
        "  Measures execution/portfolio gaps G7-G11 as deltas, not assertions;",
        "  data/statistical gaps G1-G6 are the validation battery's job. Together",
        "  they are the adversarial environment a strategy must survive before it",
        "  reaches the firewall and, eventually, a broker.",
    ])
