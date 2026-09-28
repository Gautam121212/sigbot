"""8-K event classifier — the hypothesis-testing engine (not an Ideas rescue).

Built per the research plan as a research engine that can prove the 8-K
hypothesis FALSE, weak, or strong — not a machine to force Ideas profitable.

THE SCHEMA (final research schema from day one, so the pipeline never rebuilds):
  filing -> classification -> event attributes -> point-in-time market state
         -> entry -> execution -> daily P&L -> outcome

STRUCTURAL CLASSIFICATION (works from SEC item co-occurrence, no full text):
  Item 2.01            -> M&A (acquisition/disposition of assets)
  1.01 + amended       -> Amendment (revision of prior agreement)
  1.01 + 3.02          -> Financing-equity (dilutive equity issuance)
  1.01 + 2.03          -> Financing-debt (debt obligation)
  1.01 + 5.02          -> Mgmt-change (agreement tied to leadership change)
  1.01 only            -> Pure agreement (the intended commercial/strategic deal)

FULL-TEXT CLASSIFICATION (plugs in on the user's Mac / GitHub — SEC full text is
  blocked in the build sandbox). Sub-classifies "Pure agreement" into commercial
  / strategic / government / technology-IP by keyword+LLM on the 8-K body. The
  classifier must NEVER see future price — outcome is a label, not an input.

═══════════════════════════════════════════════════════════════════════════
THE HYPOTHESIS TEST RESULT (10-day hold, ATR>6% volatile stocks, 2015-2024):

  event_class                    n      avg     MEDIAN   win    std
  Financing-debt (1.01+2.03)   1,999  +1.44%   +0.08%   50.0%   21.0
  M&A (2.01)                   1,170  -0.50%   -2.33%   42.2%   27.4
  Mgmt-change (1.01+5.02)        572  +0.96%   -2.34%   42.8%   35.3
  Pure agreement (1.01 only)   5,830  -0.51%   -2.69%   42.0%   29.2
  Amendment                      208  -1.86%   -3.74%   39.4%   33.1
  Financing-equity (1.01+3.02) 2,952  +7.78%   -3.97%   38.6%  496.1  <- tail noise

VERDICT: ★ THE 8-K HYPOTHESIS IS LARGELY FALSIFIED. ★
  Classification WORKED — the classes have distinct distributions — but NONE is
  tradeable. The best (financing-debt) has a +0.08% median: zero before costs,
  negative after. Every "good news" class (pure agreements, which contain the
  commercial/strategic deals the thesis bet on) has a NEGATIVE median. The
  +7.78% mean on financing-equity is the +26,900% penny-stock outlier (std 496%)
  — the exact tail that fooled the original model.

  The heterogeneity the plan correctly identified does NOT hide a winner. It
  explains WHY the whole bucket was flat: a mix of slightly-less-bad and worse,
  not good and bad. Sub-classifying pure agreements by full text MIGHT still
  find a commercial-contract edge inside the -2.69% median group, but the prior
  is now low. This is the research process working: a clean, early NO.

RECOMMENDATION: do NOT build Ideas as a live sleeve on structural classification.
  The one remaining test worth running (on the user's Mac, with full text) is
  whether "Pure agreement" sub-classified into genuine commercial contracts with
  a large deal-value/market-cap ratio has a positive median. If that also fails,
  ABANDON the 8-K hypothesis (Outcome B) and research a different second sleeve
  (e.g. trend-following), exactly as the plan prescribes.
"""
from __future__ import annotations

from dataclasses import dataclass


def classify_structural(items: list[str], is_amendment: bool) -> str:
    """Classify an 8-K from its SEC item codes alone (no full text needed).

    This is the point-in-time-safe structural layer. Order matters: M&A (2.01)
    and financing co-occurrences take precedence over the bare 1.01 label.
    """
    has = set(items)
    if "2.01" in has:
        return "M&A"
    if "1.01" in has and is_amendment:
        return "Amendment"
    if "1.01" in has and "3.02" in has:
        return "Financing-equity"
    if "1.01" in has and "2.03" in has:
        return "Financing-debt"
    if "1.01" in has and "5.02" in has:
        return "Mgmt-change"
    if "1.01" in has:
        return "Pure-agreement"
    return "Other"


@dataclass(frozen=True)
class ClassResult:
    event_class: str
    n: int
    avg_pct: float
    median_pct: float
    win_rate: float
    std: float

    def tradeable(self) -> bool:
        """Tradeable = positive median AND win rate >= 50% AND sane std."""
        return self.median_pct > 0.5 and self.win_rate >= 50.0 and self.std < 100


# The measured hypothesis-test results (structural classes, 10-day hold).
RESULTS = [
    ClassResult("Financing-debt", 1999, 1.44, 0.08, 50.0, 21.0),
    ClassResult("M&A", 1170, -0.50, -2.33, 42.2, 27.4),
    ClassResult("Mgmt-change", 572, 0.96, -2.34, 42.8, 35.3),
    ClassResult("Pure-agreement", 5830, -0.51, -2.69, 42.0, 29.2),
    ClassResult("Amendment", 208, -1.86, -3.74, 39.4, 33.1),
    ClassResult("Financing-equity", 2952, 7.78, -3.97, 38.6, 496.1),
]


def tradeable_classes() -> list[str]:
    return [r.event_class for r in RESULTS if r.tradeable()]


def hypothesis_falsified() -> bool:
    """No structural class is tradeable = the item-level hypothesis fails."""
    return len(tradeable_classes()) == 0


def describe() -> str:
    lines = ["8-K EVENT CLASSIFIER — hypothesis test (structural item level)", ""]
    for r in sorted(RESULTS, key=lambda x: -x.median_pct):
        mark = "TRADEABLE" if r.tradeable() else "no edge"
        lines.append(f"  [{mark:9}] {r.event_class:20} n={r.n:5}  "
                     f"avg {r.avg_pct:+.2f}%  MEDIAN {r.median_pct:+.2f}%  "
                     f"win {r.win_rate}%  std {r.std}")
    verdict = ("★ HYPOTHESIS FALSIFIED (no tradeable class) ★"
               if hypothesis_falsified() else
               f"Tradeable classes found: {tradeable_classes()}")
    lines += [
        "",
        f"  {verdict}",
        "  Classification worked (distinct distributions) but no class is",
        "  tradeable. Best is financing-debt at +0.08% median — zero before",
        "  costs. Every 'good news' class has a negative median. The bucket was",
        "  flat because it mixes slightly-less-bad with worse, not good with bad.",
        "",
        "  Remaining test (full text, on Mac): sub-classify Pure-agreement into",
        "  real commercial contracts with high deal-value/mcap. If that also",
        "  fails, ABANDON 8-K and research a different second sleeve.",
    ]
    return "\n".join(lines)
