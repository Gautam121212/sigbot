"""Skips — making swallowed failures visible.

## The hazard this closes

Twenty-six places in this codebase caught an exception and moved on without a
word. That is the most dangerous pattern here, worse than any bug found so far,
because of how it fails:

    screen 156 candidates, 40 fail to load, see 116 results

Nothing tells you a quarter of the pool never ran. You get a smaller answer that
looks exactly as confident as a complete one, and you act on it. A crash would
have been safer — a crash tells you to look.

## What replaces it

`record_skip()` counts what was skipped and why, keyed by the operation. The
count then appears in the same message as the result, so a thin answer arrives
labelled as thin:

    Screened 156 candidates: 116 usable, 0 rejected outright.
    40 could not be loaded (HTTPError 34, ValueError 6) — the screen ran on 74%
    of the pool.

The exception is still caught. A single bad symbol should not stop a scan of a
hundred and fifty. What changes is that the scan tells you it happened.

## Fail closed, not quiet

Where a partial answer would be misleading rather than merely incomplete,
`require_coverage()` raises instead. A contagion screen on 30% of the anchors is
not a weaker version of the real screen; it is a different screen whose results
do not mean what they appear to.
"""
from __future__ import annotations

import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field

_LOCK = threading.Lock()
_SKIPS: dict[str, Counter] = {}
_DETAIL: dict[str, list[str]] = {}
_SEEN: dict[str, set[str]] = {}
MAX_DETAIL = 8


@dataclass
class SkipReport:
    operation: str
    attempted: int
    skipped: int
    reasons: Counter = field(default_factory=Counter)
    examples: list[str] = field(default_factory=list)

    @property
    def completed(self) -> int:
        return self.attempted - self.skipped

    @property
    def coverage(self) -> float:
        return self.completed / self.attempted if self.attempted else 1.0

    def line(self) -> str:
        """One sentence to append to whatever the operation reports."""
        if not self.skipped:
            return ""
        kinds = ", ".join(f"{k} {v}" for k, v in self.reasons.most_common(4))
        return (f"{self.skipped} of {self.attempted} could not be processed "
                f"({kinds}) — this ran on {self.coverage:.0%} of the intended set.")

    def detail(self) -> str:
        if not self.skipped:
            return f"{self.operation}: all {self.attempted} completed."
        lines = [self.line()]
        lines += [f"  {e}" for e in self.examples[:MAX_DETAIL]]
        if self.skipped > len(self.examples):
            lines.append(f"  ... and {self.skipped - len(self.examples)} more")
        return "\n".join(lines)


def record_skip(operation: str, item: str, exc: BaseException) -> None:
    """Note that `item` was skipped during `operation`, and why.

    Deduplicated on `item`. A symbol that fails once when its returns are
    computed and again when it is scored is one skipped asset, not two — and
    counting it twice produced "16 of 28" for eight broken symbols out of
    twenty, which is a wrong number reported confidently.
    """
    with _LOCK:
        seen = _SEEN.setdefault(operation, set())
        if item in seen:
            return
        seen.add(item)
        _SKIPS.setdefault(operation, Counter())[type(exc).__name__] += 1
        det = _DETAIL.setdefault(operation, [])
        if len(det) < MAX_DETAIL:
            det.append(f"{item}: {type(exc).__name__}: {str(exc)[:90]}")


def skipped_count(operation: str) -> int:
    with _LOCK:
        return sum(_SKIPS.get(operation, Counter()).values())


def report(operation: str, attempted: int) -> SkipReport:
    with _LOCK:
        reasons = Counter(_SKIPS.get(operation, Counter()))
        examples = list(_DETAIL.get(operation, []))
    return SkipReport(operation, attempted, sum(reasons.values()), reasons, examples)


def reset(operation: str | None = None) -> None:
    with _LOCK:
        if operation is None:
            _SKIPS.clear()
            _DETAIL.clear()
            _SEEN.clear()
        else:
            _SKIPS.pop(operation, None)
            _DETAIL.pop(operation, None)
            _SEEN.pop(operation, None)


@contextmanager
def tracking(operation: str):
    """Scope a run so counts from a previous run cannot leak into this one."""
    reset(operation)
    try:
        yield
    finally:
        pass


class InsufficientCoverage(RuntimeError):
    """Raised when too little of the intended work completed to trust the result."""


def require_coverage(operation: str, attempted: int, minimum: float = 0.60) -> SkipReport:
    """Raise when coverage is too thin for the result to mean what it appears to.

    Used where a partial answer is misleading rather than merely incomplete: a
    contagion screen over a third of the anchors is not a weaker version of the
    real screen, it is a different one, and reporting its output as though it
    were the real one is the failure this guards against.
    """
    rep = report(operation, attempted)
    if attempted and rep.coverage < minimum:
        raise InsufficientCoverage(
            f"{operation} ran on {rep.coverage:.0%} of {attempted} items, below the "
            f"{minimum:.0%} needed to trust the result. {rep.line()}"
        )
    return rep
