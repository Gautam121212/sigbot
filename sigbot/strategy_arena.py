"""Strategy arena — compare strategies under identical reality, rank by EDGE.

Puts SIGBOT-INFLECTION-001, standard strategies (buy&hold, momentum, value,
quality, trend, mean-reversion, a naive control) and reconstructed GitHub
strategies into ONE environment with identical treatment, and answers the
question that actually matters: does SIGBOT have an edge, how large after
realistic costs and controls, and does it survive comparison on unseen data.

Builds only on shipped components (reality engine, validation battery, improvement
harness, strategy adapter, intelligence engine). Adds NO new alpha.

THE TRAP THIS AVOIDS — identical costs are NOT enough. Strategies have different
natural universes and frequencies: inflection trades ~12 quarterly growth
positions, mean-reversion hundreds of daily round-trips, momentum a monthly
rotation. Ranking those by raw CAGR — even under identical cost rules — measures
which strategy's natural frequency suited the specific test regime, NOT edge.
Mean-reversion looks terrible in a trending decade and brilliant in a choppy one,
and neither says anything about edge.

SO THE HEADLINE METRIC IS INCREMENTAL EDGE OVER A MATCHED CONTROL, per strategy,
against its OWN universe — inflection's "+X% over similar growth stocks that
didn't trigger", momentum's "+Y% over its own rotation universe". Those are
comparable AS EDGES even when raw returns are not. Raw CAGR is reported but
EXPLICITLY not the ranking criterion.

ANTI-MULTIPLE-TESTING: every entrant has a registered identity, locked
methodology, and fixed OOS period declared before comparison. The arena COMPARES;
it never manufactures a champion by re-looking at OOS until something wins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ValidationGate(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class EntrantProfile:
    """A registered arena entrant. Identity + locked methodology fixed BEFORE the
    comparison — no post-hoc tuning against the OOS period."""
    strategy_id: str
    universe: str                      # its OWN natural universe
    frequency: str                     # quarterly / monthly / daily etc.
    locked_oos_start: str              # declared before comparison


@dataclass(frozen=True)
class ArenaResult:
    """The full profile — NOT a single winner score. Raw performance for context,
    edge-over-control as the real metric, gates for whether it survives reality."""
    strategy_id: str
    # raw (context only, NOT the ranking criterion)
    raw_net_cagr: float
    max_drawdown: float
    sharpe: float
    sortino: float
    win_rate: float
    median_trade: float
    avg_trade: float
    turnover: float
    execution_drag_bps: float
    exposure: float
    tail_concentration: float          # mean/median ratio — >3 = a few winners
    # THE HEADLINE: edge over the strategy's OWN matched control
    matched_control_return: float
    incremental_edge: float            # raw - control, the real signal contribution
    # survival gates
    walk_forward: ValidationGate = ValidationGate.NOT_RUN
    oos: ValidationGate = ValidationGate.NOT_RUN
    monte_carlo: ValidationGate = ValidationGate.NOT_RUN
    cost_sensitivity: ValidationGate = ValidationGate.NOT_RUN
    parameter_stability: ValidationGate = ValidationGate.NOT_RUN

    def survives_reality(self) -> bool:
        """A strategy 'survives' only if its edge is real AND it passes the gates
        that were run — never on raw CAGR."""
        run = [g for g in (self.walk_forward, self.oos, self.monte_carlo,
                           self.cost_sensitivity, self.parameter_stability)
               if g != ValidationGate.NOT_RUN]
        gates_ok = all(g == ValidationGate.PASS for g in run) and bool(run)
        return self.incremental_edge > 0 and gates_ok

    def tail_dependent(self) -> bool:
        """True when the average is carried by a few outliers (the Ideas trap:
        +0.11% avg but -3.31% median). Median <= 0 with positive avg = danger."""
        return self.avg_trade > 0 and self.median_trade <= 0


# ── the arena ───────────────────────────────────────────────────────────────
@dataclass
class StrategyArena:
    """Registers entrants and compares them by EDGE, not CAGR. Reuses the shipped
    reality engine + validation battery so every entrant gets identical reality."""
    entrants: dict[str, EntrantProfile] = field(default_factory=dict)
    results: dict[str, ArenaResult] = field(default_factory=dict)

    def register(self, profile: EntrantProfile) -> None:
        """Register an entrant with a locked identity. Re-registering with a
        different OOS start is refused — no moving the goalposts."""
        existing = self.entrants.get(profile.strategy_id)
        if existing and existing.locked_oos_start != profile.locked_oos_start:
            raise ValueError(
                f"{profile.strategy_id} already registered with locked OOS "
                f"{existing.locked_oos_start}; cannot re-lock to "
                f"{profile.locked_oos_start} (anti-multiple-testing)")
        self.entrants[profile.strategy_id] = profile

    def record_result(self, result: ArenaResult) -> None:
        if result.strategy_id not in self.entrants:
            raise ValueError(f"{result.strategy_id} not registered — register "
                             "with a locked identity before recording results")
        self.results[result.strategy_id] = result

    def leaderboard_by_edge(self) -> list[ArenaResult]:
        """Ranked by INCREMENTAL EDGE, not raw CAGR. This is the whole point."""
        return sorted(self.results.values(),
                      key=lambda r: r.incremental_edge, reverse=True)

    def survivors(self) -> list[ArenaResult]:
        """Entrants whose edge is real and pass their run gates."""
        return [r for r in self.results.values() if r.survives_reality()]

    def edge_report(self, strategy_id: str) -> str:
        """The Edge Report — raw performance for context, edge as the answer,
        gates for survival, and the explicit caveat."""
        r = self.results[strategy_id]
        p = self.entrants[strategy_id]
        gate = lambda g: g.value
        return "\n".join([
            f"EDGE REPORT — {r.strategy_id}",
            f"  universe: {p.universe}  frequency: {p.frequency}  "
            f"OOS from: {p.locked_oos_start}",
            "",
            "  RAW (context only — NOT the ranking criterion):",
            f"    net CAGR {r.raw_net_cagr}%  maxDD {r.max_drawdown}%  "
            f"Sharpe {r.sharpe}  Sortino {r.sortino}",
            f"    win {r.win_rate}%  median trade {r.median_trade}%  "
            f"avg trade {r.avg_trade}%  turnover {r.turnover}",
            f"    exec drag {r.execution_drag_bps}bps  exposure {r.exposure}  "
            f"tail-concentration {r.tail_concentration}",
            "",
            "  EDGE (the real answer):",
            f"    matched-control return {r.matched_control_return}%",
            f"    incremental edge       {r.incremental_edge}%  "
            f"<- what the SIGNAL actually added",
            "",
            "  SURVIVAL GATES:",
            f"    walk-forward {gate(r.walk_forward)}  OOS {gate(r.oos)}  "
            f"Monte-Carlo {gate(r.monte_carlo)}",
            f"    cost-sensitivity {gate(r.cost_sensitivity)}  "
            f"parameter-stability {gate(r.parameter_stability)}",
            f"    survives reality: {r.survives_reality()}"
            + ("   TAIL-DEPENDENT (avg carried by outliers!)"
               if r.tail_dependent() else ""),
            "",
            "  Historical evidence != future guarantee. Even a real edge can fade.",
        ])


def describe() -> str:
    return "\n".join([
        "STRATEGY ARENA — compare under identical reality, rank by EDGE",
        "",
        "  Puts SIGBOT, standard strategies and reconstructed GitHub strategies",
        "  in one environment. Every entrant gets identical reality (costs,",
        "  slippage, liquidity, PIT rules, OOS) via the shipped reality engine +",
        "  validation battery.",
        "",
        "  THE HEADLINE METRIC IS INCREMENTAL EDGE OVER A MATCHED CONTROL, per",
        "  strategy, against its OWN universe — NOT raw CAGR. Identical costs",
        "  aren't enough: strategies have different natural frequencies/universes,",
        "  so ranking by CAGR measures regime-fit, not edge. Edge-over-control is",
        "  comparable across strategies even when raw returns are not.",
        "",
        "  A strategy survives only if its edge is real AND it passes its gates —",
        "  never on CAGR. Tail-dependence (the Ideas trap: +avg, -median) is",
        "  flagged. Anti-multiple-testing: locked identity + fixed OOS per",
        "  entrant; the arena compares, it never manufactures a champion.",
    ])
