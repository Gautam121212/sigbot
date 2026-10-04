"""Company Narrative Health — the best free non-financial research slice.

NOT "company health" (we cannot see private operations). This measures the
publicly observable NARRATIVE around a company from GDELT news data, and asks
one disciplined question: does narrative CHANGE add residual information to the
validated Inflection signal, in locked OOS, after multiple-testing correction?

Registered RESEARCH ONLY. Isolated from production. No production change
regardless of result.

SIX ATOMS (change/trajectory, never absolute tone — GDELT tone is coarse):
  sentiment_trend, sentiment_surprise, coverage_acceleration, source_breadth,
  narrative_novelty, negative_theme_persistence.

THREE STRUCTURAL ANTI-LOOKAHEAD GUARANTEES:
  1. PUBLICATION vs PROCESSING TIME. A GDELT record has both when the source was
     PUBLISHED and when GDELT PROCESSED it. A snapshot at an Inflection decision
     may use only records whose BOTH timestamps are strictly before the decision.
     Using processing-time alone leaks later-arriving coverage.
  2. BASELINE FROM THE PAST ONLY. Every atom is computed as a change relative to
     the company's OWN trailing baseline, and the baseline window ends strictly
     before the snapshot — never straddling it.
  3. NEGATIVE CONTROL. A future-shifted narrative (t+30d) must NOT appear
     predictive in a sealed test; if it does, the result is an artifact.

This module builds the apparatus and validates its guards on synthetic data. The
real backtest runs on the deployment host against real GDELT + the real trade DB
via run_company_news_health(); this module NEVER fabricates a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Atom(str, Enum):
    SENTIMENT_TREND = "sentiment_trend"
    SENTIMENT_SURPRISE = "sentiment_surprise"
    COVERAGE_ACCELERATION = "coverage_acceleration"
    SOURCE_BREADTH = "source_breadth"
    NARRATIVE_NOVELTY = "narrative_novelty"
    NEGATIVE_THEME_PERSISTENCE = "negative_theme_persistence"


# predeclared windows — small, fixed, no aggressive threshold search.
WINDOWS_DAYS = (7, 30, 90)


@dataclass(frozen=True)
class GdeltRecord:
    """One GDELT GKG document about a company. BOTH timestamps are required so
    look-ahead can be structurally prevented."""
    company: str
    published_at: datetime        # when the source article was published
    processed_at: datetime        # when GDELT recorded it (15-min batch)
    tone: float                   # coarse GDELT tone
    source_domain: str
    themes: tuple[str, ...]


def available_at(records: list[GdeltRecord], decision_time: datetime
                 ) -> list[GdeltRecord]:
    """The anti-lookahead filter: only records whose BOTH publication AND GDELT
    processing time are strictly before the decision. This is guarantee #1."""
    return [r for r in records
            if r.published_at < decision_time and r.processed_at < decision_time]


@dataclass(frozen=True)
class NarrativeSnapshot:
    """The six atoms computed at one decision time from only-available records.
    Each atom is a CHANGE relative to the company's own trailing baseline."""
    company: str
    as_of: str
    n_recent: int
    sentiment_trend: float        # recent mean tone - baseline mean tone
    sentiment_surprise: float     # (recent mean - baseline mean) / baseline std
    coverage_acceleration: float  # recent article rate / baseline rate - 1
    source_breadth: float         # distinct domains recent / recent articles
    narrative_novelty: float      # share of recent themes absent from baseline
    negative_theme_persistence: float  # recurrence of negative themes


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def compute_snapshot(records: list[GdeltRecord], company: str,
                     decision_time: datetime, recent_days: int = 7,
                     baseline_days: int = 365) -> NarrativeSnapshot:
    """Compute the six atoms at decision_time. Uses ONLY available records
    (guarantee #1) and a baseline strictly before the recent window
    (guarantee #2)."""
    avail = [r for r in available_at(records, decision_time)
             if r.company == company]
    recent_cut = decision_time - timedelta(days=recent_days)
    baseline_start = decision_time - timedelta(days=baseline_days)
    recent = [r for r in avail if r.published_at >= recent_cut]
    # baseline ends where recent begins — no straddle.
    baseline = [r for r in avail
                if baseline_start <= r.published_at < recent_cut]

    recent_tones = [r.tone for r in recent]
    base_tones = [r.tone for r in baseline]
    recent_mean = _mean(recent_tones)
    base_mean = _mean(base_tones)
    base_std = _std(base_tones)

    # coverage rate (articles/day) recent vs baseline
    recent_rate = len(recent) / max(recent_days, 1)
    base_rate = len(baseline) / max(baseline_days - recent_days, 1)
    cov_accel = (recent_rate / base_rate - 1.0) if base_rate > 0 else 0.0

    breadth = (len({r.source_domain for r in recent}) / len(recent)
               if recent else 0.0)

    base_themes = {t for r in baseline for t in r.themes}
    recent_themes = [t for r in recent for t in r.themes]
    novelty = (sum(1 for t in recent_themes if t not in base_themes)
               / len(recent_themes)) if recent_themes else 0.0

    neg_recent = [t for r in recent if r.tone < 0 for t in r.themes]
    neg_counts: dict[str, int] = {}
    for t in neg_recent:
        neg_counts[t] = neg_counts.get(t, 0) + 1
    persistence = (sum(1 for c in neg_counts.values() if c >= 2)
                   / len(neg_counts)) if neg_counts else 0.0

    return NarrativeSnapshot(
        company=company, as_of=decision_time.isoformat(), n_recent=len(recent),
        sentiment_trend=round(recent_mean - base_mean, 4),
        sentiment_surprise=round((recent_mean - base_mean) / base_std, 4)
        if base_std > 0 else 0.0,
        coverage_acceleration=round(cov_accel, 4),
        source_breadth=round(breadth, 4),
        narrative_novelty=round(novelty, 4),
        negative_theme_persistence=round(persistence, 4))


# ── the conditional residual backtest (apparatus; runs on real data) ────────
@dataclass(frozen=True)
class AtomResult:
    atom: Atom
    window_days: int
    n_signals: int
    dev_separation: float         # high-narrative minus low-narrative, dev split
    oos_separation: float         # same, locked OOS
    t_stat: float
    negative_control_separation: float  # future-shifted; must be ~0
    survives: bool


@dataclass
class CompanyNewsHealthResult:
    inflection_baseline_oos: float = 0.0
    atoms: list[AtomResult] = field(default_factory=list)
    t_bar_corrected: float = 0.0  # Bonferroni for the number of atom x window cells
    verdict: str = "NOT_RUN"      # SURVIVED / REJECTED / INCONCLUSIVE / NOT_RUN
    data_note: str = ""

    def survivors(self) -> list[AtomResult]:
        return [a for a in self.atoms if a.survives]


def evaluate_atom(atom: Atom, window_days: int, *, n_signals: int,
                  dev_separation: float, oos_separation: float,
                  oos_mean: float, oos_std: float,
                  negative_control_separation: float,
                  t_bar: float) -> AtomResult:
    """Decide whether one atom x window survives. Requires: positive separation
    in BOTH dev and oos, a t-stat clearing the corrected bar, AND a negative
    control near zero (the future-shifted narrative must not predict)."""
    import math
    t = (oos_mean / (oos_std / math.sqrt(n_signals))) \
        if oos_std > 0 and n_signals > 1 else 0.0
    neg_control_clean = abs(negative_control_separation) < 0.5 * abs(oos_separation) \
        if oos_separation != 0 else abs(negative_control_separation) < 0.1
    survives = (dev_separation > 0 and oos_separation > 0 and t >= t_bar
                and neg_control_clean)
    return AtomResult(atom, window_days, n_signals, round(dev_separation, 3),
                      round(oos_separation, 3), round(t, 3),
                      round(negative_control_separation, 3), survives)


def corrected_t_bar(n_cells: int) -> float:
    import statistics
    alpha = 0.05 / max(1, n_cells)
    return round(statistics.NormalDist().inv_cdf(1 - alpha / 2), 3)


def describe() -> str:
    return "\n".join([
        "COMPANY NARRATIVE HEALTH — the best free non-financial research slice",
        "",
        "  RESEARCH ONLY, isolated from production. Measures the publicly",
        "  observable NARRATIVE (GDELT news) around a company — NOT its private",
        "  operations — and tests whether narrative CHANGE adds residual",
        "  information to the validated Inflection signal, in locked OOS, after",
        "  multiple-testing correction.",
        "",
        "  SIX atoms (change vs the company's OWN baseline, never absolute tone):",
        "  sentiment trend/surprise, coverage acceleration, source breadth,",
        "  narrative novelty, negative-theme persistence. Windows: 7/30/90d.",
        "",
        "  THREE anti-lookahead guarantees: publication-AND-processing-time",
        "  filter; baseline strictly before the recent window; a future-shifted",
        "  NEGATIVE CONTROL that must not predict. The real backtest runs on the",
        "  deployment host against real GDELT + the real trade DB; this module",
        "  builds and validates the apparatus and NEVER fabricates a verdict.",
    ])
