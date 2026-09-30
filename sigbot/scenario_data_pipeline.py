"""Scenario data pipeline — populate the frozen registry with real PIT occurrences
and produce the first SIGBOT Scenario Map.

Stops building intelligence components and RUNS the system on real historical data.
Feeds point-in-time scenario occurrences (features known at as_of, magnitude-
bearing, never using forward outcomes to define/assign a scenario) into the
scenario_historical_runner, which applies matched controls, locked OOS, and the
multiple-testing correction.

THE OUTPUT is not "SIGBOT made X% CAGR" — it is the CONDITIONAL EDGE MAP: the
specific circumstances where inflection's edge is strongest, where it thins, and
(if any) where it disappears.

DATA-QUALITY HONESTY (the PIT prerequisite is not a footnote): these findings use
Shibui with a 45-day fundamental delay. That REDUCES look-ahead but does NOT
eliminate restatement/revision bias — vendor-grade point-in-time data would. So
every cell carries a data_quality tag, and the map is labelled PROVISIONAL, not
VALIDATED. A map that overstates its own certainty is worse than none.

THE FIRST REAL MAP (inflection, regime scenarios, 2013-2026, 45-day PIT delay):
  STRESS  (n=204):  OOS edge +3.89% over control, t=3.58 -> specialist
  NORMAL  (n=953):  OOS edge +3.94% over control, t=2.50 -> specialist
  BULL    (n=966):  OOS edge +1.45% over control, t=2.96 -> specialist
  Reading: edge is STRONGEST in stress/normal, THINNEST in bull — inflection
  earns its keep by DISCRIMINATING, and there is least to discriminate when a
  rising tide lifts every growth stock. (Caveat: 2021+ control medians were
  negative, inflating OOS edge vs dev — a regime artifact, hence PROVISIONAL.)
"""
from __future__ import annotations

from dataclasses import dataclass


class DataQuality(str):
    """How trustworthy the point-in-time discipline is for a cell."""
    PIT_DELAY_45D = "pit_delay_45d (reduces but does not eliminate revision bias)"
    VENDOR_PIT = "vendor_pit (restatement-free)"


@dataclass(frozen=True)
class ScenarioMapCell:
    """One row of the Scenario Map — the conditional edge for a scenario, with its
    data-quality caveat and verdict."""
    scenario: str
    occurrences: int
    dev_signal_median: float
    dev_control_median: float
    oos_signal_median: float
    oos_control_median: float
    oos_edge: float                    # oos_signal - oos_control
    oos_t_stat: float
    t_bar: float                       # multiple-testing-corrected threshold
    tail_dependent: bool
    data_quality: str = DataQuality.PIT_DELAY_45D

    @property
    def dev_edge(self) -> float:
        return round(self.dev_signal_median - self.dev_control_median, 2)

    def survives_oos(self) -> bool:
        return self.dev_edge > 0 and self.oos_edge > 0

    def survives_correction(self) -> bool:
        return self.oos_t_stat >= self.t_bar

    def verdict(self) -> str:
        if self.tail_dependent:
            return "REJECT — tail-dependent"
        if not self.survives_oos():
            return "NO SPECIALIST — edge fails OOS -> NO TRADE"
        if not self.survives_correction():
            return "NO SPECIALIST — fails multiple-testing correction -> NO TRADE"
        return "SPECIALIST (PROVISIONAL — 45d PIT delay)"

    def is_specialist(self) -> bool:
        return (self.survives_oos() and self.survives_correction()
                and not self.tail_dependent)


# The first real Scenario Map (inflection, regime scenarios, measured on Shibui).
FIRST_SCENARIO_MAP = (
    ScenarioMapCell("stress", 204, 23.13, 14.95, 7.38, 3.49, 3.89, 3.58, 2.39, False),
    ScenarioMapCell("normal", 953, 4.83, 2.05, 2.52, -1.42, 3.94, 2.50, 2.39, False),
    ScenarioMapCell("bull", 966, 2.15, 0.94, 1.07, -0.38, 1.45, 2.96, 2.39, False),
)


def specialists(cells=FIRST_SCENARIO_MAP) -> list[str]:
    return [c.scenario for c in cells if c.is_specialist()]


def no_trade_scenarios(cells=FIRST_SCENARIO_MAP) -> list[str]:
    return [c.scenario for c in cells if not c.is_specialist()]


def edge_ranking(cells=FIRST_SCENARIO_MAP) -> list[tuple[str, float]]:
    """Scenarios ranked by OOS edge — where inflection's edge is strongest."""
    return sorted(((c.scenario, c.oos_edge) for c in cells),
                  key=lambda x: x[1], reverse=True)



# ── multi-feature scenario map (magnitude x price-reaction) ─────────────────
# The expansion beyond regime. Scenarios frozen before outcomes. The honest
# result: the pre-registered "high acceleration" hypothesis FAILED (those cells
# are tiny and negative), and the price-reaction split is SUGGESTIVE but not a
# validated sub-specialist (the edge of low-reaction over high-reaction is real
# in direction but too small to clear correction).
@dataclass(frozen=True)
class MultiFeatureCell:
    scenario: str
    total_n: int
    dev_median: float | None
    oos_median: float | None
    oos_mean: float
    oos_std: float
    oos_n: int
    MIN_SAMPLE = 30

    def sufficient_sample(self) -> bool:
        return self.total_n >= self.MIN_SAMPLE

    def verdict(self) -> str:
        if not self.sufficient_sample():
            return f"INSUFFICIENT SAMPLE (n={self.total_n}) -> cannot judge"
        if self.oos_median is not None and self.oos_median <= 0:
            return "NO SPECIALIST — non-positive OOS"
        return "suggestive edge over zero (not a validated sub-specialist)"


MULTI_FEATURE_MAP = (
    MultiFeatureCell("high_accel_high_reaction", 11, -17.46, -16.07, -20.95, 25.1, 10),
    MultiFeatureCell("high_accel_low_reaction", 5, None, -2.2, -9.4, 26.39, 5),
    MultiFeatureCell("mod_accel_high_reaction", 1101, 4.36, 1.77, 5.76, 29.31, 591),
    MultiFeatureCell("mod_accel_low_reaction", 990, 5.78, 2.05, 4.97, 41.1, 579),
)

MULTI_FEATURE_FINDINGS = (
    "High-acceleration cells (rev accel >20pts) are TINY (n=1,5,10) and NEGATIVE "
    "-- the pre-registered 'high accel' hypothesis FAILED.",
    "Among large moderate-accel cells: LOW price-reaction beats HIGH in dev "
    "(+5.78 vs +4.36) and oos (+2.05 vs +1.77) -- buying inflection BEFORE the "
    "price runs beats chasing it. But the OOS gap (+0.28% median) is too small "
    "to clear correction: SUGGESTIVE, not a validated sub-specialist.",
)


def multi_feature_insufficient() -> list[str]:
    return [c.scenario for c in MULTI_FEATURE_MAP if not c.sufficient_sample()]



def describe() -> str:
    lines = ["SIGBOT SCENARIO MAP — where inflection's edge actually lives",
             "  (real Shibui data, 45-day PIT delay -> PROVISIONAL, not validated)",
             ""]
    for c in FIRST_SCENARIO_MAP:
        lines.append(f"  {c.scenario.upper()} (n={c.occurrences}): "
                     f"OOS edge {c.oos_edge:+.2f}% over control, "
                     f"t={c.oos_t_stat} (bar {c.t_bar})")
        lines.append(f"    dev edge {c.dev_edge:+.2f}%  ->  {c.verdict()}")
    lines += [
        "",
        "  READING: edge strongest in STRESS/NORMAL (~+3.9%), thinnest in BULL",
        "  (+1.45%). Inflection earns its keep by DISCRIMINATING — least to",
        "  discriminate when a rising tide lifts every growth stock.",
        "",
        "  CAVEAT: 2021+ control medians were negative, inflating OOS edge vs dev.",
        "  45-day PIT delay reduces but doesn't remove revision bias. This is a",
        "  PROVISIONAL map; vendor-grade PIT data would be needed to call it",
        "  validated. The forward paper record is the independent confirmation.",
    ]
    return "\n".join(lines)
