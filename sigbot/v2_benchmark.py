"""V2.0-BENCHMARK — the frozen sustained-inflection foundation.

Locked per the research plan Phase 1: no further optimization of the core edge
while other sleeves are researched. This is the clean benchmark every future
sleeve is measured against. All numbers are the validated trade-level / portfolio
/ Monte-Carlo / matched-control results, not the retired annual figures.

═══════════════════════════════════════════════════════════════════════════
FROZEN 2026-09-28. Do not edit these numbers; they are the benchmark of record.

RULES (exact):
  Signal:  gross margin rising 3 consecutive quarters
           AND revenue growth accelerating 2 consecutive quarters
  Entry:   45 days after quarter-end (point-in-time safe)
  Hold:    63 trading days (~90 calendar days)
  Universe: full US common stock, price > $3
  Costs:   30 bps round-trip

TRADE-LEVEL (1,703 real trades, 2013-2024):
  avg gross +6.87% / net +6.57% per trade / win 59.4% / std 31.5%
  worst -87.4% / best +603.8%

PORTFOLIO (139 months, geometric monthly, 10bps/mo drag):
  CAGR 21.9% / vol 11.3% / Sharpe 1.58 / Sortino 1.67 / Calmar 1.24
  max DD 17.6% (10-month) / worst month -8.0% / 78% winning months

MONTE CARLO (10k sims — the HONEST forward view):
  median CAGR 14.1% (realized 21.9% was top-quartile / lucky sequence)
  max DD median 23.8% / 95th pct 39.9%
  P(negative long-term) 0.35% / P(CAGR>20%) 15.8%

MATCHED CONTROL (real alpha, not beta):
  signal median +3.74% vs same-universe control +1.45% = +2.29% median alpha

WALK-FORWARD: positive every year 2013-2024.

VERDICT: robust, real alpha, honestly worth ~14% forward with up-to-40% DD.
This is Level 1 of the 30% ladder. Additional sleeves are measured by whether
they ADD return the inflection sleeve doesn't already have (low correlation),
NOT by their standalone CAGR.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Benchmark:
    version: str = "V2.0-BENCHMARK"
    frozen_date: str = "2026-09-28"
    # trade level
    trades: int = 1703
    net_per_trade: float = 6.57
    win_rate: float = 59.4
    # portfolio
    cagr_historical: float = 21.9
    sharpe: float = 1.58
    sortino: float = 1.67
    calmar: float = 1.24
    max_dd: float = 17.6
    # honest forward (Monte Carlo)
    cagr_forward: float = 14.1
    max_dd_p95: float = 39.9
    # alpha
    median_alpha_vs_control: float = 2.29


BENCHMARK = Benchmark()


def is_frozen() -> bool:
    return True


def sleeve_adds_value(new_cagr: float, correlation: float) -> bool:
    """A second sleeve earns inclusion by DIVERSIFICATION, not raw CAGR.

    The plan's rule: a 15% sleeve at 0.1 correlation beats a 25% sleeve at 0.9.
    Accept a sleeve if it is positive-return AND meaningfully uncorrelated.
    """
    return new_cagr > 8.0 and correlation < 0.5


def describe() -> str:
    b = BENCHMARK
    return "\n".join([
        f"{b.version} (frozen {b.frozen_date}) — sustained-inflection",
        "",
        f"  Trade level: {b.trades:,} trades, +{b.net_per_trade}% net/trade, "
        f"{b.win_rate}% win",
        f"  Portfolio:   CAGR {b.cagr_historical}% (historical), Sharpe {b.sharpe}, "
        f"max DD {b.max_dd}%",
        f"  HONEST fwd:  ~{b.cagr_forward}% CAGR (Monte Carlo median), "
        f"max DD 95th pct {b.max_dd_p95}%",
        f"  Real alpha:  +{b.median_alpha_vs_control}% median vs matched control",
        "",
        "  LOCKED. No core-model optimization while other sleeves are built.",
        "  A new sleeve earns inclusion by low correlation + positive return,",
        "  NOT by standalone CAGR (a 15% sleeve at 0.1 corr beats 25% at 0.9).",
    ])
