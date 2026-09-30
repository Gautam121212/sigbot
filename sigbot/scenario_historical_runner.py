"""Historical scenario runner — where does SIGBOT's edge actually live?

Takes the FROZEN scenario registry + the strategy set + the reality engine and
produces the full scenario x strategy matrix: for each scenario, how often it
occurred, its magnitude, forward outcomes, each strategy's conditional result,
the matched control, the incremental edge, tail-dependence, and locked-OOS
survival. Discovery and MEASUREMENT only — no optimization, no re-defining
scenarios after seeing results, no picking the highest return.

THE DISCIPLINE THIS ENFORCES (the runner sits exactly where this project keeps
overfitting): it measures MANY cells — scenarios x strategies x horizons. Run
enough and some show a big "edge" from pure chance. Three structural controls:

  1. FROZEN INPUTS. The scenario registry must be frozen and the strategy set
     fixed before the run. A run against an unfrozen registry raises.

  2. LOCKED OOS. Each cell's edge is discovered on the dev split and CONFIRMED on
     an OOS split it never touched. A cell that shows edge in dev but not OOS is
     not a specialist.

  3. MULTIPLE-TESTING CORRECTION (the usually-missing piece). A cell is judged
     against a significance bar tightened for the NUMBER of cells tested
     (Bonferroni). A raw t-stat that would pass alone does NOT pass when it was
     one of 40 comparisons. "Validated specialist" = survives AFTER correction,
     not looked-good-once.

The output is a finding to be frozen and re-tested, never an action. If no
strategy clears the corrected bar for a scenario, the honest result is NO
SPECIALIST — which is as important as finding one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .scenario_intelligence import ScenarioLibrary, ScenarioRegistry


@dataclass(frozen=True)
class CellResult:
    """One scenario x strategy cell: its conditional edge and whether it survives
    reality AND multiple-testing correction."""
    scenario_id: str
    strategy_id: str
    n_occurrences: int
    dev_median: float
    oos_median: float
    matched_control_median: float
    incremental_edge: float            # oos_median - control
    t_stat: float
    tail_dependent: bool
    survives_oos: bool                 # positive edge in BOTH dev and oos
    survives_correction: bool          # passes the multiple-testing-adjusted bar

    def is_validated_specialist(self) -> bool:
        return (self.survives_oos and self.survives_correction
                and not self.tail_dependent and self.incremental_edge > 0)


@dataclass(frozen=True)
class ScenarioVerdict:
    """The per-scenario answer: the best validated specialist, or NO SPECIALIST."""
    scenario_id: str
    n_occurrences: int
    best_specialist: str | None        # None = no strategy cleared the bar
    best_edge: float
    all_cells: tuple[CellResult, ...]

    def has_specialist(self) -> bool:
        return self.best_specialist is not None


def _t_stat(mean: float, std: float, n: int) -> float:
    if std <= 0 or n <= 1:
        return 0.0
    return mean / (std / math.sqrt(n))


def _bonferroni_threshold(n_cells: int) -> float:
    """The t-stat a cell must beat, tightened for the number of comparisons. A
    single test needs ~1.96 (5%); 40 tests need ~3.0+ so the family-wise error
    stays at 5%. Approximated from the corrected alpha."""
    if n_cells <= 1:
        return 1.96
    # alpha_corrected = 0.05 / n_cells; convert to an approximate z threshold
    import statistics
    alpha = 0.05 / n_cells
    # inverse-normal (two-sided) — the multiple-testing-corrected z threshold
    z = statistics.NormalDist().inv_cdf(1 - alpha / 2)
    return round(z, 3)


@dataclass
class ScenarioHistoricalRunner:
    """Runs the scenario x strategy matrix with frozen inputs, locked OOS, and a
    multiple-testing-corrected significance bar."""
    registry: ScenarioRegistry
    library: ScenarioLibrary
    strategy_ids: tuple[str, ...] = ()
    _verdicts: dict[str, ScenarioVerdict] = field(default_factory=dict)

    def run(self, cell_data) -> dict[str, ScenarioVerdict]:
        """cell_data(scenario_id, strategy_id) -> dict with dev/oos/control
        distributions. The runner supplies the discipline; cell_data supplies the
        measured numbers (from the reality engine / library)."""
        if not self.registry.is_frozen():
            raise ValueError("registry must be frozen before the historical run "
                             "— unfrozen definitions enable outcome-conditioned "
                             "scenario selection (leak 2)")
        scenario_ids = self.registry.all_ids()
        n_cells = len(scenario_ids) * max(1, len(self.strategy_ids))
        t_bar = _bonferroni_threshold(n_cells)

        for sid in scenario_ids:
            cells: list[CellResult] = []
            for strat in self.strategy_ids:
                data = cell_data(sid, strat)
                if data is None or data.get("n", 0) == 0:
                    continue
                cell = self._build_cell(sid, strat, data, t_bar)
                cells.append(cell)
            specialists = [c for c in cells if c.is_validated_specialist()]
            best = max(specialists, key=lambda c: c.incremental_edge,
                       default=None)
            self._verdicts[sid] = ScenarioVerdict(
                scenario_id=sid,
                n_occurrences=cells[0].n_occurrences if cells else 0,
                best_specialist=best.strategy_id if best else None,
                best_edge=best.incremental_edge if best else 0.0,
                all_cells=tuple(cells))
        return dict(self._verdicts)

    def _build_cell(self, sid: str, strat: str, data: dict,
                    t_bar: float) -> CellResult:
        dev_med = data["dev_median"]
        oos_med = data["oos_median"]
        control = data["control_median"]
        edge = oos_med - control
        t = _t_stat(data["oos_mean"], data["oos_std"], data["n"])
        tail = data["oos_mean"] > 0 and oos_med <= 0
        survives_oos = dev_med > control and oos_med > control
        survives_corr = t >= t_bar
        return CellResult(sid, strat, data["n"], dev_med, oos_med, control,
                          round(edge, 3), round(t, 3), tail,
                          survives_oos, survives_corr)

    def specialists(self) -> dict[str, str]:
        """Scenarios that have a validated specialist -> that strategy."""
        out: dict[str, str] = {}
        for sid, v in self._verdicts.items():
            if v.best_specialist is not None:
                out[sid] = v.best_specialist
        return out

    def no_specialist_scenarios(self) -> list[str]:
        """Scenarios where NO strategy cleared the corrected bar — NO TRADE."""
        return [sid for sid, v in self._verdicts.items() if not v.has_specialist()]

    def report(self) -> str:
        lines = ["HISTORICAL SCENARIO AUDIT — where the edge actually lives", ""]
        for sid, v in sorted(self._verdicts.items()):
            if v.has_specialist():
                lines.append(f"  {sid} (n={v.n_occurrences}): specialist "
                             f"{v.best_specialist}, edge +{v.best_edge}%")
            else:
                lines.append(f"  {sid} (n={v.n_occurrences}): NO SPECIALIST "
                             "(no strategy cleared the corrected bar) -> NO TRADE")
        return "\n".join(lines)


def describe() -> str:
    return "\n".join([
        "HISTORICAL SCENARIO RUNNER — where does SIGBOT's edge live?",
        "",
        "  Produces the scenario x strategy matrix from the FROZEN registry: per",
        "  scenario, each strategy's conditional edge vs a matched control, with",
        "  locked-OOS confirmation and tail-dependence flags.",
        "",
        "  THREE STRUCTURAL CONTROLS (this is where the project keeps overfitting):",
        "    1. Frozen inputs — an unfrozen registry raises before the run.",
        "    2. Locked OOS — edge must hold in dev AND an untouched OOS split.",
        "    3. Multiple-testing correction — the significance bar tightens with",
        "       the number of cells (Bonferroni). A t-stat that passes alone",
        "       fails when it was one of 40 comparisons. 'Validated specialist'",
        "       means survives AFTER correction, not looked-good-once.",
        "",
        "  Measurement only — no optimization, no re-defining scenarios after",
        "  results. NO SPECIALIST (no validated strategy -> NO TRADE) is as",
        "  important a finding as a specialist.",
    ])
