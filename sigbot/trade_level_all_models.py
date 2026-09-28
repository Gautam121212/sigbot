"""Trade-level backtest — crypto, news, ideas. The honest reckoning.

Following the research plan, each model's edge was rebuilt as a REAL trade-level
backtest (every setup = one trade, actual signed forward return, costs applied,
median vs mean tail check). The results overturn the annual-resolution report.

═══════════════════════════════════════════════════════════════════════════
CRYPTO — coiled-spring, 3-day hold (CoinGecko, 20 coins, 1 year)
  26 trades. Gross +2.01% / net +1.61%. MEDIAN +0.56%. Win 50%.
  Worst -6.7%, best +47.3%, std 10.3%.
  VERDICT: real but thin and tail-carried. Mean is ~4x median — a few winners
  make it. 50% win rate = coin flip on direction; it is a magnitude bet. Far
  from the annual "+18% CAGR" smooth story, but not broken. Low trade count is
  a real concern for statistical confidence.

═══════════════════════════════════════════════════════════════════════════
NEWS — deeply-oversold + big-beat, 10-day hold (312 trades, 2015-2026)
  Gross +4.25% / net +4.05%. MEDIAN +1.67%. Win 54.8%.
  Worst -81.8%, best +884.7%, std 54.3%.
  VERDICT: positive and the median is positive (+1.67%), which is better than
  crypto or ideas. But the mean is 2.5x the median — one +884% trade does heavy
  lifting. A real edge, modest, tail-influenced. The honest per-trade number is
  ~+1.7% typical, not the compounding the annual report implied.

═══════════════════════════════════════════════════════════════════════════
IDEAS — material-agreement 8-K on volatile small-cap, 10-day hold
  18,127 trades. Gross +0.61% / NET +0.11%. MEDIAN -3.31%. Win 40.9%.
  Worst -97.3%, best +26,900%, std 203.6%.
  VERDICT: ★ THE EDGE IS FALSE AS BUILT. ★ The typical (median) trade LOSES
  3.31%. Most trades lose (41% win rate). Net return is ~zero. The entire
  positive average is one or two penny-stock moonshots (+26,900%) in 18,000
  trades — unrepeatable and uninvestable. The annual report's +19.6% CAGR /
  4.13 Sharpe for ideas was an ARTIFACT of averaging in untradeable tail
  winners. Trading every Item 1.01 on a volatile small-cap is a LOSING strategy.

  THE FIX (exactly what the research plan prescribed): Item 1.01 is a broad
  category (M&A, financing, licensing, amendments — economically opposite
  events). The edge does not exist for the whole bucket. It must be rebuilt to
  classify the actual agreement type and trade only the economically-positive,
  surprising subtypes. Until then, ideas should NOT trade live.

═══════════════════════════════════════════════════════════════════════════
OVERALL HONEST RECKONING:
  - stocks/ventures (sustained-inflection): REAL, +6.57% net/trade, holds up.
  - news: REAL but modest, +1.7% median/trade.
  - crypto: real but thin, tail-carried, low confidence.
  - ideas: FALSE as built — median trade loses money. Needs the 8-K classifier
    rebuild before it can trade.
The annual report overstated every model. Trade-level truth is lower and more
volatile everywhere, and one model (ideas) does not have an edge at all yet.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTradeStats:
    model: str
    total_trades: int
    avg_gross_pct: float
    avg_net_pct: float
    median_pct: float
    win_rate: float
    worst_pct: float
    best_pct: float
    std_dev: float
    verdict: str
    tradeable: bool


CRYPTO = ModelTradeStats(
    "crypto", 26, 2.01, 1.61, 0.56, 50.0, -6.7, 47.3, 10.3,
    "Real but thin and tail-carried; magnitude bet, low trade count", True)

NEWS = ModelTradeStats(
    "news", 312, 4.25, 4.05, 1.67, 54.8, -81.8, 884.7, 54.3,
    "Real, modest, positive median +1.67%; tail-influenced", True)

IDEAS = ModelTradeStats(
    "ideas", 18127, 0.61, 0.11, -3.31, 40.9, -97.3, 26900.0, 203.6,
    "FALSE as built — median trade loses 3.31%; edge is untradeable penny-stock "
    "tail. Needs the 8-K event-type classifier before trading.", False)

ALL_STATS = {"crypto": CRYPTO, "news": NEWS, "ideas": IDEAS}


def untradeable_models() -> list[str]:
    """Models whose edge does NOT survive trade-level testing."""
    return [m for m, s in ALL_STATS.items() if not s.tradeable]


def describe() -> str:
    lines = ["TRADE-LEVEL RECKONING — crypto, news, ideas (the honest numbers)", ""]
    for s in ALL_STATS.values():
        mark = "TRADEABLE" if s.tradeable else "★ FALSE EDGE ★"
        lines.append(f"[{mark}] {s.model.upper()} — {s.total_trades:,} real trades")
        lines.append(f"    gross +{s.avg_gross_pct}% / net +{s.avg_net_pct}% / "
                     f"MEDIAN {s.median_pct:+}% / win {s.win_rate}%")
        lines.append(f"    worst {s.worst_pct}% / best +{s.best_pct}% / "
                     f"std {s.std_dev}%")
        lines.append(f"    {s.verdict}")
        lines.append("")
    lines.append(f"UNTRADEABLE (edge is false as built): {untradeable_models()}")
    lines.append("")
    lines.append("The annual report overstated every model. IDEAS has no real")
    lines.append("edge — its median trade loses money; the positive average is")
    lines.append("untradeable penny-stock moonshots. It must not trade live until")
    lines.append("rebuilt with 8-K event classification (per the research plan).")
    return "\n".join(lines)
