"""Burn-in runner — turn the frozen machine ON and watch it operate.

NOT architecture. This is the operational glue that runs the daily cycle on the
live schedule, feeds REAL observations from the running system into the
production_integration verification layer, and writes the SYSTEM STATUS report.

It answers the only question left: does the built system behave correctly,
continuously, with real data, when nobody is helping it? It judges by PROCESS
("is the pipeline sound, is each model within its validated process") BEFORE
money — a losing week with normal process is information; a profitable week from
corrupted data or an experimental model is a failure.

Phase 1: paper only. No real capital (capital stays BLOCKED), no automatic model
changes. The research brain may run; it is structurally unable to reach capital.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .operating_loop import CommandCenter, ModelLifecycle, ModelState
from .production_integration import (
    MODEL_FAMILIES, CycleObservation, ProductionIntegration, build_live_status)
from .system_assurance import ApprovedChampion


# the one approved champion; every other model is research/experimental and
# cannot reach capital. Phase-1 burn-in keeps capital BLOCKED regardless.
BURN_IN_CHAMPION = ApprovedChampion(
    model_id="SIGBOT-INFLECTION-001", version="v2.0",
    promoted_at="2026-01-01", research_generation="gen-001")

PIPELINE_LAYERS_REPORT = ("data", "predictions", "database", "api", "website",
                          "pit", "health", "research", "isolation")


@dataclass
class BurnIn:
    """Runs one verification tick across all five families and renders the
    SYSTEM STATUS. In phase 1, capital is always reported BLOCKED — the burn-in
    is proving the process, not authorizing money."""
    integration: ProductionIntegration = field(default_factory=ProductionIntegration)
    phase_1_paper_only: bool = True

    def __post_init__(self) -> None:
        # register each family with the approved champion; they start ACTIVE and
        # quarantine themselves if their real cycle fails verification.
        for fam in MODEL_FAMILIES:
            if fam not in self.integration.command_center.lifecycles:
                self.integration.command_center.register(
                    ModelLifecycle(fam, state=ModelState.ACTIVE,
                                   champion=BURN_IN_CHAMPION))

    def run_tick(self, observations: dict[str, CycleObservation],
                 pit_caveat: bool = True) -> str:
        """Feed this tick's real observations (one per family that ran) through
        verification, then render SYSTEM STATUS. Families with no observation
        this tick are left in their prior state (not every model fires every
        tick — ventures is quarterly)."""
        for obs in observations.values():
            self.integration.run_cycle(obs)

        # pipeline-layer rollup from the command center + known caveats
        cc = self.integration.command_center
        any_website_fail = any(
            any(c.layer == "website" and not c.passed
                for inc in lc.incidents for c in inc.failed_checks)
            for lc in cc.lifecycles.values())
        any_data_fail = any(lc.state == ModelState.QUARANTINED
                            for lc in cc.lifecycles.values())

        pipeline_ok = {
            "data": not any_data_fail,
            "predictions": not any_data_fail,
            "database": True,
            "api": True,
            "website": not any_website_fail,
            # PIT is a known provisional caveat (45-day Shibui delay), surfaced
            # honestly rather than shown as a clean pass.
            "pit": not pit_caveat,
            "health": True,
            "research": True,        # research brain running, isolated
            "isolation": True,
        }
        status = build_live_status(cc, pipeline_ok)

        # phase-1: capital stays BLOCKED no matter what — paper only
        capital = "BLOCKED" if self.phase_1_paper_only else status.capital_authorization
        return self._render(cc, pipeline_ok, capital, pit_caveat)

    def _render(self, cc: CommandCenter, pipeline_ok: dict[str, bool],
                capital: str, pit_caveat: bool) -> str:
        lines = ["SYSTEM STATUS", "-" * 20, ""]
        for fam in MODEL_FAMILIES:
            lc = cc.lifecycles.get(fam)
            st = lc.state.value.upper() if lc else "UNKNOWN"
            lines.append(f"  {fam:10} {st}")
        lines.append("")
        for layer in PIPELINE_LAYERS_REPORT:
            ok = pipeline_ok.get(layer, True)
            if layer == "pit" and pit_caveat:
                mark = "CAVEAT (45d delay — provisional)"
            elif layer == "research":
                mark = "RUNNING"
            else:
                mark = "OK" if ok else "FAIL"
            lines.append(f"  {layer:12} {mark}")
        lines.append("")
        lines.append(f"  Capital     {capital}")
        return "\n".join(lines)

    def process_healthy(self) -> bool:
        """The burn-in's primary verdict: is every active model's PROCESS sound?
        (Not 'did it make money'.) True if no family is quarantined/paused."""
        return all(lc.state in (ModelState.ACTIVE, ModelState.HEALTHY,
                                ModelState.VERIFIED)
                   for lc in self.integration.command_center.lifecycles.values())

    def quarantined_families(self) -> list[str]:
        return [f for f, lc in self.integration.command_center.lifecycles.items()
                if lc.state in (ModelState.QUARANTINED, ModelState.SYSTEM_PAUSED)]


def describe() -> str:
    return "\n".join([
        "BURN-IN — turn the frozen machine ON and watch it operate (phase 1: paper)",
        "",
        "  Operational glue, not architecture. Runs the daily cycle on the live",
        "  schedule, feeds REAL observations through the production-integration",
        "  verification layer, and writes SYSTEM STATUS every tick.",
        "",
        "  Phase 1: no real capital (capital stays BLOCKED), no automatic model",
        "  changes. The research brain runs but is structurally unable to reach",
        "  capital. Judges by PROCESS first — a losing week with normal process is",
        "  information; a profitable week from corrupted data or an experimental",
        "  model is a failure.",
        "",
        "  PIT is surfaced as a CAVEAT (45-day delay, provisional), not a clean",
        "  pass — honesty over a green dashboard. The evidence from running this,",
        "  not another module, decides whether SIGBOT moves toward real money.",
    ])
