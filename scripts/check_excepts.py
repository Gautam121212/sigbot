#!/usr/bin/env python3
"""Phase 1, item 4 — enforce the exception rule in CI.

    python scripts/check_excepts.py          # fails the build on a violation
    python scripts/check_excepts.py --list   # show every catch and its verdict

The rule, from the build document: no bare `except:`, and every broad
`except Exception` must either re-raise or record the failure. A catch that
does neither turns a broken run into a quiet one, which is the single most
expensive class of bug this project has hit — twenty-six of them at one point,
any of which could have let a screen run on 60% of the pool and look complete.

Honest constraint: this reads the syntax tree, not the semantics. A handler that
calls `record_skip` with the wrong operation name passes here and is still
wrong. It catches the shape of the mistake, not every instance of it.

Largest risk: passing this check feeling like proof that failures are visible.
It proves only that each handler does *something*. Whether that something
reaches you is what `skips.report()` is for.

Test gap: `--list` output formatting is unverified; only the verdicts are.
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("sigbot", "scripts")

# A handler is satisfied by any of these appearing inside it.
RECORDERS = ("record_skip", "logger", "logging", "log_run", "print",
             "traceback", "warnings")

# A handler that returns a value describing the failure is legitimate and
# invisible to an AST scan — `doctor.check_quarantine` returns a Check saying it
# could not look. Rather than guess, the rule is: justify it in writing on the
# except line. Silence is what is banned, not breadth.
MARKER = "# handled:"


@dataclass(frozen=True)
class Handler:
    path: str
    line: int
    kind: str            # "bare" | "broad" | "specific"
    verdict: str         # "ok" | "violation"
    reason: str

    def render(self) -> str:
        mark = "  ok  " if self.verdict == "ok" else " FAIL "
        return f"[{mark}] {self.path}:{self.line} {self.kind} — {self.reason}"


def _names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            out.add(child.id)
        elif isinstance(child, ast.Attribute):
            out.add(child.attr)
    return out


def _handles(node: ast.ExceptHandler) -> tuple[bool, bool]:
    """(re-raises, records) for one handler, ignoring nested handlers."""
    reraises = any(isinstance(n, ast.Raise) for n in ast.walk(node))
    called = _names(node)
    records = bool(called & set(RECORDERS))
    return reraises, records


def inspect_file(path: Path) -> list[Handler]:
    rel = str(path.relative_to(ROOT))
    try:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Handler(rel, exc.lineno or 0, "parse", "violation",
                        f"could not parse: {exc.msg}")]

    out: list[Handler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            out.append(Handler(rel, node.lineno, "bare", "violation",
                               "bare except catches KeyboardInterrupt and SystemExit "
                               "as well as errors. Name the exception."))
            continue

        caught = _names(node.type) if node.type else set()
        broad = bool(caught & {"Exception", "BaseException"})
        if not broad:
            out.append(Handler(rel, node.lineno, "specific", "ok",
                               "catches a named exception"))
            continue

        justified = (0 < node.lineno <= len(lines)
                     and MARKER in lines[node.lineno - 1])
        reraises, records = _handles(node)
        if justified:
            out.append(Handler(rel, node.lineno, "broad", "ok",
                               "justified in writing on the except line"))
            continue
        if reraises or records:
            out.append(Handler(rel, node.lineno, "broad", "ok",
                               "re-raises" if reraises else "records the failure"))
        else:
            out.append(Handler(rel, node.lineno, "broad", "violation",
                               "catches Exception and neither re-raises nor records "
                               "it. A broken run becomes a quiet one. Either "
                               f"record it, or justify it with '{MARKER} reason'."))
    return out


def scan() -> list[Handler]:
    out: list[Handler] = []
    for pkg in PACKAGES:
        for path in sorted((ROOT / pkg).rglob("*.py")):
            out.extend(inspect_file(path))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="show every handler")
    args = ap.parse_args(argv)

    handlers = scan()
    violations = [h for h in handlers if h.verdict == "violation"]

    if args.list:
        for h in handlers:
            print(h.render())
        print()

    kinds = {k: sum(1 for h in handlers if h.kind == k)
             for k in ("bare", "broad", "specific")}
    print(f"{len(handlers)} handlers: {kinds['specific']} specific, "
          f"{kinds['broad']} broad, {kinds['bare']} bare")

    if not violations:
        print("Every broad handler either re-raises or records the failure.")
        return 0

    print(f"\n{len(violations)} violation(s):")
    for h in violations:
        print("  " + h.render())
    print("\nEvery catch must re-raise or write to the skip ledger. A handler "
          "that does neither hides the failure it caught.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
