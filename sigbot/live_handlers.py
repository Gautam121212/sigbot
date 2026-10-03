"""Live dispatch handlers — the real integrations the OperatingLoop calls.

Starts with activate_pending (the safest: no new prediction, just fills a pending
next-session entry at the ACTUAL session open). This is where the overnight-drift
exclusion becomes true on the real ledger, not just in unit tests.

Each handler is wired one at a time and tested against the real shadow DB before
the coordinator is switched over. Lineage: every activation records which run_id
filled it, so a prediction traces run -> event -> admission -> activation ->
resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .market_scheduler import Family
from .operating_loop_v2 import DispatchHandlers
from .shadow import ShadowLedger


def _session_open_price(market, symbol: str, effective_at: datetime
                        ) -> float | None:
    """The real session-open price at/after the execution point. Uses the first
    bar's open on or after effective_at. Returns None if no bar is available yet
    (the session hasn't opened or data isn't in) — the caller then leaves the
    entry pending, never guessing a price."""
    try:
        start = (effective_at.date()).isoformat()
        end = (effective_at.date()).isoformat()
        bars = market.history(symbol, start, end)
    except Exception:  # noqa: BLE001  # handled: no data -> leave pending
        return None
    if bars is None or len(bars) == 0 or "open" not in getattr(bars, "columns", []):
        return None
    try:
        # first bar at/after the effective date; its open is the session open.
        val = float(bars["open"].iloc[0])
        return val if val > 0 else None
    except (IndexError, ValueError, TypeError):  # noqa: BLE001  # handled
        return None


@dataclass
class LiveActivationHandler(DispatchHandlers):
    """Real activate_pending: fills pending next-session stock entries at the
    actual session open. Pure — creates no predictions, only activates existing
    ones, and refuses to back-date before the execution point."""
    ledger: ShadowLedger = None          # type: ignore[assignment]
    market: object = None                # provider with .history(sym,start,end)
    now_fn: object = None
    _lineage: list[dict] = field(default_factory=list)

    def _now(self) -> datetime:
        return self.now_fn() if self.now_fn else datetime.now(timezone.utc)  # type: ignore[operator]

    def activate_pending(self, family: Family, run_id: str) -> int:
        if family != Family.STOCKS or self.ledger is None or self.market is None:
            return 0
        now = self._now()
        activated = 0
        for row in self.ledger.pending_entries("stocks"):
            eff = row.get("decision_effective_at")
            if not eff:
                continue
            eff_dt = datetime.fromisoformat(eff)
            # only activate once the execution point has actually arrived.
            if now < eff_dt:
                continue
            price = _session_open_price(self.market, row["symbol"], eff_dt)
            if price is None:
                continue                 # session open not available yet; wait
            if self.ledger.activate_entry(row["id"], price, executed_at=now):
                activated += 1
                # lineage: run -> prediction -> activation price
                self._lineage.append({
                    "run_id": run_id, "prediction_id": row["id"],
                    "symbol": row["symbol"], "activation_price": price,
                    "activated_at": now.isoformat(),
                    "decision_effective_at": eff})
        return activated

    def lineage(self) -> list[dict]:
        return list(self._lineage)


def describe() -> str:
    return "\n".join([
        "LIVE HANDLERS — real integrations the OperatingLoop calls",
        "",
        "  activate_pending (first, safest): fills pending next-session stock",
        "  entries at the ACTUAL session open (first bar's open at/after the",
        "  execution point). Creates NO predictions; refuses to activate before",
        "  the execution point; leaves the entry pending when the open price isn't",
        "  available yet rather than guessing. This makes the overnight-drift",
        "  exclusion true on the real ledger: realised return is measured from the",
        "  session open, never the overnight scan price.",
        "",
        "  Records lineage per activation (run_id -> prediction_id -> price) so a",
        "  live prediction traces run -> event -> admission -> activation ->",
        "  resolution. Other handlers (stocks predict, resolver, crypto, ventures,",
        "  ideas, news dedup) are wired next, one at a time, each tested before the",
        "  coordinator switches to OperatingLoop.tick().",
    ])
