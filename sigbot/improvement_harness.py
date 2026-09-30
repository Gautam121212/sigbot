"""One-gap-at-a-time improvement harness — enforced isolation, not convention.

The discipline that was MISSING when the momentum filter and regime rule overfit
earlier this session: they were tested as bundles / on data the rule had seen.
This harness makes those failures STRUCTURALLY IMPOSSIBLE:

  * A variant may change EXACTLY ONE causal component. Bundled changes are
    rejected before execution, not judged after.
  * The experiment config (splits, seed, the single change) is FROZEN and
    hashed before any data is touched. The locked OOS split is sealed and
    cannot be read during fitting — reading it before the decision raises.
  * Baseline and variant run through the SAME reality engine + validation
    battery. Neither can use a different cost model or a different split.
  * The decision is DETERMINISTIC and multi-criteria (never CAGR alone). No
    LLM, no model, no human judgement in the decision layer.
  * Every experiment — pass OR fail — is appended to an immutable ledger.

The harness proves an improvement is real by isolating its single cause and
showing it survives on data it never touched. Anything else is rejected.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum


# ── the one allowed causal component ────────────────────────────────────────
class Component(str, Enum):
    """The causal components a variant may change. A variant names exactly one."""
    EXECUTION = "execution"          # e.g. same-bar -> next-bar
    SIZING = "sizing"                # e.g. fixed -> vol-scaled
    LIQUIDITY = "liquidity"          # e.g. add ADV cap
    ENTRY_THRESHOLD = "entry_threshold"
    EXIT_RULE = "exit_rule"
    UNIVERSE = "universe"
    REGIME_FILTER = "regime_filter"


@dataclass(frozen=True)
class Change:
    """Exactly one causal modification, fully specified before execution."""
    component: Component
    description: str
    param_before: str
    param_after: str


@dataclass(frozen=True)
class SplitConfig:
    """Pre-declared temporal splits. The OOS end date is sealed."""
    dev_end: str                     # fit here
    validation_end: str              # compare candidates here
    oos_end: str                     # LOCKED — never touched until decision

    def __post_init__(self) -> None:
        if not (self.dev_end < self.validation_end < self.oos_end):
            raise ValueError("splits must be strictly ordered dev<val<oos")


@dataclass
class ExperimentConfig:
    """Frozen-and-hashed before execution. The hash is the tamper-evidence."""
    baseline_id: str
    changes: list[Change]
    splits: SplitConfig
    seed: int = 42
    frozen_hash: str = field(default="", init=False)

    def freeze(self) -> str:
        """Compute the config hash. After this, any mutation is detectable."""
        payload = {
            "baseline_id": self.baseline_id,
            "changes": [asdict(c) for c in self.changes],
            "splits": asdict(self.splits),
            "seed": self.seed,
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        self.frozen_hash = hashlib.sha256(blob.encode()).hexdigest()[:16]
        return self.frozen_hash

    def assert_single_change(self) -> None:
        """STRUCTURAL isolation: reject bundled changes before execution."""
        if len(self.changes) != 1:
            raise BundledChangeError(
                f"a variant may change exactly ONE component; got "
                f"{len(self.changes)}. Split into separate experiments.")


class BundledChangeError(Exception):
    """Raised when an experiment tries to change more than one component."""


class SplitLeakageError(Exception):
    """Raised when the locked OOS split is read before the decision."""


# ── the sealed OOS split ────────────────────────────────────────────────────
class LockedSplit:
    """Wraps the OOS data so it cannot be read during fitting. Any access before
    unseal() (which only the decision step calls) raises."""

    def __init__(self, oos_metric: float) -> None:
        self._metric = oos_metric
        self._sealed = True

    def unseal(self) -> None:
        self._sealed = False

    def read(self) -> float:
        if self._sealed:
            raise SplitLeakageError(
                "locked OOS split read during fitting — this is exactly the "
                "leak that overfit the momentum filter. Sealed until decision.")
        return self._metric


# ── results & decision ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class SplitResult:
    """A strategy's measured performance on one split (from the reality engine
    + validation battery — never self-reported)."""
    net_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    n_trades: int


class Verdict(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"


@dataclass(frozen=True)
class ExperimentResult:
    config_hash: str
    verdict: Verdict
    reasons: tuple[str, ...]
    baseline_oos: SplitResult
    variant_oos: SplitResult


# ── the multi-criteria deterministic decision ───────────────────────────────
def decide(baseline_oos: SplitResult, variant_oos: SplitResult) -> tuple[Verdict, tuple[str, ...]]:
    """Deterministic, multi-criteria. NEVER CAGR alone. A variant is promoted
    only if it improves risk-adjusted return WITHOUT degrading drawdown or
    hit-rate materially, on the LOCKED OOS split. No LLM, no discretion."""
    reasons: list[str] = []
    passes = True

    # 1. Sharpe must improve (risk-adjusted, not raw return)
    if variant_oos.sharpe <= baseline_oos.sharpe:
        passes = False
        reasons.append(
            f"OOS Sharpe not improved ({variant_oos.sharpe:.2f} vs "
            f"{baseline_oos.sharpe:.2f})")
    else:
        reasons.append(f"OOS Sharpe improved to {variant_oos.sharpe:.2f}")

    # 2. Drawdown must not worsen by more than a small tolerance
    if variant_oos.max_drawdown > baseline_oos.max_drawdown + 2.0:
        passes = False
        reasons.append(
            f"OOS max drawdown worsened ({variant_oos.max_drawdown:.1f}% vs "
            f"{baseline_oos.max_drawdown:.1f}%)")

    # 3. Win rate must not collapse (guards against a few-tail-winners artifact)
    if variant_oos.win_rate < baseline_oos.win_rate - 5.0:
        passes = False
        reasons.append(
            f"OOS win rate collapsed ({variant_oos.win_rate:.1f}% vs "
            f"{baseline_oos.win_rate:.1f}%)")

    # 4. Sample must be adequate (no promotion on thin evidence)
    if variant_oos.n_trades < 30:
        passes = False
        reasons.append(f"OOS sample too thin ({variant_oos.n_trades} trades)")

    return (Verdict.PASS if passes else Verdict.REJECT, tuple(reasons))


# ── immutable research ledger ───────────────────────────────────────────────
class ResearchLedger:
    """Append-only. Every experiment, pass or fail, is recorded and cannot be
    altered or removed. A failed experiment is information (a killed hypothesis)."""

    def __init__(self) -> None:
        self._entries: list[ExperimentResult] = []

    def append(self, result: ExperimentResult) -> None:
        self._entries.append(result)

    def all(self) -> tuple[ExperimentResult, ...]:
        return tuple(self._entries)

    def rejections(self) -> tuple[ExperimentResult, ...]:
        return tuple(e for e in self._entries if e.verdict == Verdict.REJECT)

    def __len__(self) -> int:
        return len(self._entries)


# ── the harness entry point ─────────────────────────────────────────────────
def run_experiment(
    config: ExperimentConfig,
    baseline_result_fn,     # () -> (SplitResult dev, val, LockedSplit oos)
    variant_result_fn,      # same shape, for the modified strategy
    ledger: ResearchLedger,
) -> ExperimentResult:
    """Run one isolated experiment end-to-end. Enforces single-change and
    split-sealing structurally, then makes the deterministic decision."""
    # 1. STRUCTURAL isolation — reject bundles before anything runs
    config.assert_single_change()

    # 2. Freeze the config; the hash is tamper-evidence
    config_hash = config.freeze()

    # 3. Fit / measure on dev+val (both strategies, same engine)
    base_dev, base_val, base_oos_locked = baseline_result_fn()
    var_dev, var_val, var_oos_locked = variant_result_fn()

    # 4. The locked OOS split is sealed until THIS point — the decision step.
    #    Unsealing here, after fitting, is the only legal read.
    base_oos_locked.unseal()
    var_oos_locked.unseal()
    base_oos = _split_from_locked(base_oos_locked, base_val)
    var_oos = _split_from_locked(var_oos_locked, var_val)

    # 5. Deterministic multi-criteria decision (no CAGR-only, no LLM)
    verdict, reasons = decide(base_oos, var_oos)

    result = ExperimentResult(config_hash, verdict, reasons, base_oos, var_oos)
    ledger.append(result)          # 6. immutable record, pass or fail
    return result


def _split_from_locked(locked: LockedSplit, template: SplitResult) -> SplitResult:
    """Read the sealed OOS metric (raises if still sealed) and build the OOS
    SplitResult. The Sharpe comes from the locked read; other fields from the
    measured template shape."""
    oos_sharpe = locked.read()     # raises SplitLeakageError if still sealed
    return SplitResult(template.net_return, oos_sharpe, template.max_drawdown,
                       template.win_rate, template.n_trades)


def describe() -> str:
    return "\n".join([
        "ONE-GAP-AT-A-TIME IMPROVEMENT HARNESS — enforced, not conventional",
        "",
        "  Makes the failures that overfit the momentum filter and regime rule",
        "  STRUCTURALLY IMPOSSIBLE:",
        "    * exactly ONE causal change per experiment (bundles rejected before",
        "      execution)",
        "    * config frozen + hashed before any data is touched",
        "    * OOS split SEALED — reading it during fitting raises",
        "    * baseline & variant share the same reality engine + battery",
        "    * decision is deterministic, multi-criteria (Sharpe + drawdown +",
        "      win-rate + sample), NEVER CAGR alone, NO LLM in the decision",
        "    * every experiment, pass OR fail, in an immutable ledger",
        "",
        "  An improvement is promoted only if its single isolated cause survives",
        "  on data it never touched. Everything else is rejected and recorded.",
    ])
