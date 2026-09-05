"""Requirements must cover what the code imports.

`pytest` was missing from requirements.txt while SETUP.md told you to run the
test suite at step 5. That step could never have worked on a clean machine, and
nothing caught it because the sandbox it was written in already had pytest
installed. This test fails if the two ever drift apart again.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Distribution name where it differs from the import name.
ALIASES = {"sklearn": "scikit-learn", "yaml": "pyyaml", "dateutil": "python-dateutil"}

# Local packages and any module inside scripts/, which tests import directly by
# name after adding scripts/ to sys.path. Those are ours, not dependencies.
LOCAL = {"sigbot", "tests", "scripts", "conftest"} | {
    p.stem for p in (ROOT / "scripts").glob("*.py")}


def _declared() -> set[str]:
    text = (ROOT / "requirements.txt").read_text()
    return {re.split(r"[><=!\[]", line)[0].strip().lower()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")}


def _imported() -> set[str]:
    """Top-level modules imported anywhere, read from the AST.

    Parsed rather than grepped: a regex over the source also matches the word
    "from" inside a docstring, which is how an earlier version of this check
    reported `roughly` and `them` as missing dependencies.
    """
    found: set[str] = set()
    for folder in ("sigbot", "tests", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        found.add(node.module.split(".")[0])
    return {ALIASES.get(m, m) for m in found}


def test_requirements_file_exists():
    """A cleanup once deleted it, which broke step 4 of the setup guide."""
    assert (ROOT / "requirements.txt").exists()


def test_pytest_is_declared():
    """The setup guide tells you to run the suite. It has to be installable."""
    assert "pytest" in _declared()


def test_every_third_party_import_is_declared():
    stdlib = set(sys.stdlib_module_names)
    missing = sorted(_imported() - _declared() - stdlib - LOCAL)
    assert not missing, (
        f"imported but not in requirements.txt: {missing}. "
        "A clean machine would fail on these."
    )


def test_nothing_declared_is_unused():
    """An unused pin is a slower install and a lie about what this needs."""
    declared = _declared()
    imported = _imported()
    # Optional live-data extras are imported lazily inside functions; the AST
    # walk finds those too, so they should still appear.
    unused = sorted(declared - imported - {"scikit-learn"})
    assert not unused, f"declared but never imported: {unused}"


def test_the_test_suite_writes_nothing_into_the_project():
    """Tests must not leave databases in the user's folder.

    `build_export`'s watchlist argument defaults to "watchlist.db" in the
    current directory. A test that omitted it left a real, seeded 100-asset
    board behind — and `run_screen --apply` then found a full board, added
    nothing, and silently discarded the screen it had just spent twenty minutes
    computing.

    Compared against a snapshot taken before the session, not against an empty
    folder. On a working install shadow.db, watchlist.db and patterns.db are the
    user's own record, and failing on those turns a correct check into one you
    learn to ignore.
    """
    from tests.conftest import databases_at_start

    created = sorted({p.name for p in ROOT.glob("*.db")} - databases_at_start())
    assert not created, (
        f"the suite created {created} in the project folder. Every test that "
        "touches a database must pass an explicit tmp_path."
    )


def test_project_document_stays_true():
    """PROJECT.md quotes real thresholds. A doc that drifts from the code is
    worse than no doc, because it is trusted."""
    doc = (ROOT / "PROJECT.md").read_text()

    from sigbot.adapt import COOLDOWN_DAYS, MIN_MISSES, MIN_SHARE
    from sigbot.config import POOL
    from sigbot.screener import CRITERIA
    from sigbot.watchlist import RULES

    for name, (weight, _) in CRITERIA.items():
        assert f"| {name} | {weight:.0f} |" in doc, f"{name} weight drifted"
    assert f"{RULES.green_min_n}+ checks" in doc
    assert f"{RULES.drop_min_n}+ checks" in doc
    assert f"{MIN_MISSES}+ misses" in doc
    assert f"{MIN_SHARE:.0%}+ of them" in doc
    assert f"{COOLDOWN_DAYS} days" in doc
    assert f"{len(POOL)} candidates" in doc


def test_project_document_only_names_real_commands():
    import sigbot.runner as runner

    doc = (ROOT / "PROJECT.md").read_text()
    for cmd in set(re.findall(r"python -m sigbot\.runner (\w+)", doc)):
        assert hasattr(runner, f"run_{cmd}"), f"PROJECT.md names a missing job: {cmd}"
    for script in set(re.findall(r"(scripts/[\w_]+\.(?:py|sh))", doc)):
        assert (ROOT / script).exists(), f"PROJECT.md names a missing file: {script}"


def test_project_document_keeps_the_gaps_section():
    """The 'what is lacking' section is the useful half. It must not quietly
    disappear as things get fixed."""
    doc = (ROOT / "PROJECT.md").read_text()
    assert "## 5. What is lacking" in doc
    for gap in ("Survivorship bias", "point-in-time news archive",
                "not wired", "Not built at all"):
        assert gap in doc, f"the gaps section lost: {gap}"
