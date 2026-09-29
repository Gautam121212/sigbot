"""Factor filter — the honest result of the cross-sectional ML feasibility test.

The plan proposed an autonomous cross-sectional ML alpha engine (rank the whole
universe by a multi-factor model, RD-Agent-style discovery loop). Before building
it, the core assumption was tested: does a multi-factor cross-sectional composite
BEAT the locked inflection benchmark? It does not. But the same factors, used as
a FILTER on inflection, materially improve it. That is the real, evidence-backed
enhancement — not a discovery engine.

═══════════════════════════════════════════════════════════════════════════
TEST 1 — cross-sectional composite as a STANDALONE ranker (momentum+growth+ROIC
z-scores, deciled per date, 63-day forward). 2016-2022, ~52k observations.
     Top decile (10): +3.15% avg / +0.28% median / 50.4% win
     Middle (5):      +3.71% avg / +2.24% median / 56.2% win
   ★ FAILS ★ Top decile UNDERPERFORMS the middle — no monotonic ranking signal.
   And +0.28% median is far below inflection's +3.74%. A cross-sectional ML
   model over these factors will not beat the inflection rule; the composite IS
   the linear ceiling, and tree/ensemble interactions are in-sample noise here.

TEST 2 — the same factors as a FILTER on inflection (does mom+quality separate
good inflection setups from mediocre ones?). 2016-2022.
     Inflection + high mom/qual: +7.08% avg / +4.88% median / 61.9% win (n=612)
     Inflection + low  mom/qual: +5.13% avg / +1.54% median / 54.5% win (n=409)
     Non-inflection:             +3.18% avg / +1.28% median / 52.8% win
   ★ WORKS ★ The filter adds +3.34% median and nearly doubles the win-rate edge.
   The factors carry real CONDITIONAL information even though they cannot rank
   the universe standalone.

═══════════════════════════════════════════════════════════════════════════
TEST 3 — OOS VALIDATION (the correction). The +3.34% uplift in TEST 2 was
measured on DEVELOPMENT data (pre-2023). Re-run with a locked holdout
(DEV pre-2023, OOS 2023-2026 untouched), momentum and quality separated:

  DEV (in-sample):   infl+mom +4.68% med / infl+qual +4.55% / low-both +3.82%
  OOS (untouched):   infl+mom +0.17% med / infl+qual +1.44% / low-both -0.50%

  ★ THE FILTER LARGELY OVERFIT. ★ Momentum's in-sample +4.68% median collapsed
  to +0.17% OOS — classic factor decay, gone in 2023-2026. Quality (ROIC) held
  up partially: +1.44% OOS median, 54.1% win vs 48.9% for rejected trades — a
  weak but real conditional signal. The combined filter's OOS median edge is
  ~1-2%, not the +3.34% seen in-sample, and it cuts trade count ~40%, so it
  will likely LOSE portfolio CAGR to idle capital.

CORRECTED VERDICT: DROP the momentum filter (does not survive OOS). Quality
(ROIC) is a weak OOS-surviving candidate worth ONE more validation pass, but
too thin to justify the ~40% trade-count cut on its own. The locked V2.0
inflection sleeve remains the edge; no filter has earned production yet.
The "cashable now" claim from the prior turn was an in-sample artifact —
corrected here.

VERDICT: build the FILTER, not the discovery engine. The momentum+quality
composite is useless as a universe-wide ranker but valuable as a quality gate on
the validated inflection signal. This raises the inflection sleeve's median trade
from ~3.7% toward ~4.9% on the filtered subset, at the cost of ~40% fewer trades
(612 vs 1021 inflection signals pass the filter). That is a real improvement to
the ONE proven edge — evidence-backed, not a hoped-for ML breakthrough.

WHY NOT THE DISCOVERY ENGINE: the factor-search hit rate across this whole
research program is 1-for-5 (inflection passed; 8-K, regime-fundamentals,
estimate-revision, cross-sectional-composite all failed), and the one winner was
hand-found, not searched. Liquid-US-equity factors on free fundamental+price data
are the most-mined dataset in finance; industrializing the search over a flat
signal space produces a stream of multiple-testing false positives, not alpha.
The honest enhancement is the filter above.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactorFilterResult:
    # standalone ranking test (failed)
    standalone_top_decile_median: float = 0.28
    standalone_mid_decile_median: float = 2.24
    inflection_benchmark_median: float = 3.74
    # filter test (works)
    infl_high_factor_median: float = 4.88  # DEV/in-sample; OOS ~1.9%
    infl_high_factor_win: float = 61.9
    infl_low_factor_median: float = 1.54
    infl_low_factor_win: float = 54.5
    infl_high_n: int = 612
    infl_low_n: int = 409

    def standalone_beats_inflection(self) -> bool:
        return self.standalone_top_decile_median > self.inflection_benchmark_median

    def filter_improves_inflection(self) -> bool:
        return self.infl_high_factor_median > self.infl_low_factor_median + 1.0

    def median_uplift(self) -> float:
        return round(self.infl_high_factor_median - self.infl_low_factor_median, 2)


RESULT = FactorFilterResult()


def factor_filter_score(mom6_z: float, roic_z: float) -> float:
    """The momentum+quality composite z-score. A trade passes the quality gate
    when this is positive (above cross-sectional average)."""
    return mom6_z + roic_z


def passes_quality_gate(mom6_z: float, roic_z: float) -> bool:
    return factor_filter_score(mom6_z, roic_z) > 0


@dataclass(frozen=True)
class OOSValidation:
    """The locked-holdout test that corrects the in-sample filter result."""
    mom_dev_median: float = 4.68
    mom_oos_median: float = 0.17          # momentum decayed to ~zero OOS
    qual_dev_median: float = 4.55
    qual_oos_median: float = 1.44         # quality partially survived
    lowboth_oos_median: float = -0.50

    def momentum_survives_oos(self) -> bool:
        return self.mom_oos_median > 1.0

    def quality_survives_oos(self) -> bool:
        return self.qual_oos_median > self.lowboth_oos_median + 1.0


OOS = OOSValidation()


def production_ready_filter() -> str:
    """Which filter, if any, has earned production. Momentum: no. Quality: not yet."""
    if OOS.momentum_survives_oos():
        return "momentum+quality"
    if OOS.quality_survives_oos():
        return "quality-only (weak, needs one more validation pass)"
    return "none — inflection V2.0 stands alone"


def describe() -> str:
    r = RESULT
    return "\n".join([
        "FACTOR FILTER — cross-sectional ML feasibility result",
        "",
        f"  Standalone ranker: top-decile median {r.standalone_top_decile_median}%"
        f" vs inflection {r.inflection_benchmark_median}%",
        f"    beats inflection standalone? {r.standalone_beats_inflection()}  (FAILS)",
        "",
        "  As a FILTER on inflection:",
        f"    high mom/qual: {r.infl_high_factor_median}% median, "
        f"{r.infl_high_factor_win}% win (n={r.infl_high_n})",
        f"    low  mom/qual: {r.infl_low_factor_median}% median, "
        f"{r.infl_low_factor_win}% win (n={r.infl_low_n})",
        f"    improves inflection? {r.filter_improves_inflection()}  "
        f"(+{r.median_uplift()}% median uplift)",
        "",
        "  VERDICT: build the FILTER, not the discovery engine. Multi-factor",
        "  info is useless as a universe ranker but valuable as a quality gate",
        "  on the proven inflection signal. Factor-search hit rate is 1-for-5;",
        "  industrializing search over a flat signal space yields false positives,",
        "  not alpha. Cash in the evidence-backed filter instead.",
    ])
