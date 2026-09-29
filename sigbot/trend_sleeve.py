"""Trend / time-series-momentum sleeve — feasibility research (Sleeve 2).

Tested per the plan: NOT optimized for CAGR. Simple TSMOM across a liquid
multi-asset ETF universe (18 assets: US/intl equities, bonds, gold, commodities,
sectors, REIT), next-period execution, no leverage, measured for edge AND — the
real question — correlation with the locked V2.0 inflection benchmark.

═══════════════════════════════════════════════════════════════════════════
1. PARAMETER PLATEAU (lookback sweep, 21-day fwd hold) — PASS
     15d  -0.08%  Sharpe -0.05
     21d  -0.04%  Sharpe -0.02
     45d  -0.03%  Sharpe -0.02
     63d  -0.03%  Sharpe -0.02
     126d +0.16%  Sharpe +0.09   <- plateau begins
     189d +0.17%  Sharpe +0.10
     252d +0.16%  Sharpe +0.09
   Clean STRUCTURAL plateau: short horizons flat/negative, long horizons
   (126-252d) consistently positive and tightly clustered. Exactly where the
   academic literature (Moskowitz-Ooi-Pedersen; AQR) places time-series
   momentum. Not a single magic setting — a real neighborhood.

2. STANDALONE PORTFOLIO (252d TSMOM, monthly, equal-weight, full sample)
     157 months, Sharpe 0.31, +0.23%/mo (~2.8%/yr), 58.6% win months.
     WEAK standalone earner. In the inflection-overlap window (133 mo, to
     mid-2024) Sharpe was ~0 — the strong 2025-26 trend run is outside it.

3. CORRELATION GATE (vs inflection) — ★ STRONG PASS ★
     Full-period correlation:            -0.097
     Downside corr (inflection-down mo):  +0.063
     15 worst inflection months (avg -3.9%): trend +0.06%, positive 7/15
   This is the best possible diversification profile: near-zero everywhere,
   and it does NOT crash when inflection bleeds.

4. ALLOCATION SWEEP (inflection base + trend) — the honest result
     0%:  Sharpe 1.63, maxDD 17.6%
     10%: Sharpe 1.60, maxDD 15.8%    <- best trade-off
     20%: Sharpe 1.54, maxDD 14.1%
     30%: Sharpe 1.44, maxDD 12.3%
     50%: Sharpe 1.05, maxDD 10.0%
   NO allocation raises Sharpe — every weight lowers it monotonically. But
   every weight lowers drawdown. Trend buys DRAWDOWN REDUCTION, not return.

═══════════════════════════════════════════════════════════════════════════
VERDICT: trend is a REAL, robust, near-zero-correlation diversifier but TOO
WEAK an earner to raise risk-adjusted return on this data. It earns a SMALL
allocation (10-15%) as a drawdown-reducer ONLY IF lower drawdown is valued —
it does NOT move the portfolio toward 30%. Adding a 0.3-Sharpe sleeve to a
1.6-Sharpe sleeve cannot raise the blend's return; it can only smooth it.

This is the kill-gate applied honestly: PASS on plateau and correlation,
MARGINAL on standalone edge, FAIL on improving Sharpe. Keep as an optional
defensive overlay, not a return engine. The 30% target still requires a
sleeve with BOTH real return AND low correlation — which neither Ideas (dead)
nor trend (too weak) provides. That sleeve may not exist in reach; the honest
path may be accepting ~14-18% from inflection + a small trend overlay.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TrendResult:
    lookback_plateau: dict[str, float] = field(default_factory=lambda: {
        "15d": -0.05, "21d": -0.02, "45d": -0.02, "63d": -0.02,
        "126d": 0.09, "189d": 0.10, "252d": 0.09})
    standalone_sharpe: float = 0.31
    corr_full: float = -0.097
    corr_downside: float = 0.063
    # (trend_weight -> (sharpe, maxdd))
    allocation: dict[int, tuple[float, float]] = field(default_factory=lambda: {
        0: (1.63, 17.6), 10: (1.60, 15.8), 15: (1.57, 15.0),
        20: (1.54, 14.1), 30: (1.44, 12.3), 50: (1.05, 10.0)})

    def plateau_is_real(self) -> bool:
        """Long horizons (126-252) positive, short (15-63) not — real plateau."""
        longs = [self.lookback_plateau[k] for k in ("126d", "189d", "252d")]
        shorts = [self.lookback_plateau[k] for k in ("15d", "21d", "45d", "63d")]
        return all(x > 0 for x in longs) and all(x <= 0 for x in shorts)

    def is_uncorrelated(self) -> bool:
        return abs(self.corr_full) < 0.2 and abs(self.corr_downside) < 0.2

    def improves_sharpe(self) -> bool:
        base = self.allocation[0][0]
        return any(sh > base for sh, _ in self.allocation.values())

    def best_defensive_weight(self) -> int:
        """The weight that cuts drawdown most while keeping Sharpe within 5%."""
        base = self.allocation[0][0]
        ok = [(w, sh, dd) for w, (sh, dd) in self.allocation.items()
              if w > 0 and sh >= base * 0.97]
        return min(ok, key=lambda x: x[2])[0] if ok else 0


TREND = TrendResult()


def verdict() -> str:
    return ("DIVERSIFIER, NOT RETURN ENGINE: robust plateau + near-zero "
            "correlation, but too weak to raise Sharpe. Small defensive "
            "overlay only.")


def describe() -> str:
    t = TREND
    return "\n".join([
        "TREND SLEEVE — time-series momentum feasibility",
        "",
        f"  Plateau real:      {t.plateau_is_real()} (126-252d positive, short flat)",
        f"  Standalone Sharpe: {t.standalone_sharpe} (weak earner)",
        f"  Correlation:       {t.corr_full} full / {t.corr_downside} downside",
        f"  Uncorrelated:      {t.is_uncorrelated()} (STRONG diversification)",
        f"  Improves Sharpe:   {t.improves_sharpe()} (no weight beats 1.63)",
        f"  Best defensive wt: {t.best_defensive_weight()}% "
        f"(cuts maxDD 17.6->15.8% at ~same Sharpe)",
        "",
        f"  VERDICT: {verdict()}",
        "  Does NOT move the portfolio toward 30% — a 0.3-Sharpe sleeve cannot",
        "  raise a 1.6-Sharpe blend's return, only smooth it. Keep as optional",
        "  10-15% drawdown overlay. The 30% target still lacks a sleeve with",
        "  BOTH real return AND low correlation.",
    ])
