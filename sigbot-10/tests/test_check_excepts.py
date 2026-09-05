"""Tests for the exception guard.

Twenty-six silently swallowed exceptions once meant a screen could run on 60%
of the pool and look complete. This is the check that stops the twenty-seventh.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_excepts as ce  # noqa: E402


def _scan(tmp_path, source: str):
    f = tmp_path / "sample.py"
    f.write_text(source)
    original = ce.ROOT
    ce.ROOT = tmp_path
    try:
        return ce.inspect_file(f)
    finally:
        ce.ROOT = original


def test_the_codebase_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_excepts.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_a_bare_except_is_always_a_violation(tmp_path):
    h = _scan(tmp_path, "try:\n    x = 1\nexcept:\n    pass\n")
    assert h[0].kind == "bare" and h[0].verdict == "violation"
    assert "KeyboardInterrupt" in h[0].reason


def test_a_silent_broad_except_is_a_violation(tmp_path):
    h = _scan(tmp_path, "try:\n    x = 1\nexcept Exception:\n    x = 0\n")
    assert h[0].kind == "broad" and h[0].verdict == "violation"
    assert "quiet one" in h[0].reason


def test_re_raising_is_accepted(tmp_path):
    h = _scan(tmp_path, "try:\n    x = 1\nexcept Exception:\n    raise\n")
    assert h[0].verdict == "ok" and "re-raises" in h[0].reason


@pytest.mark.parametrize("call", ["record_skip('a','b',exc)", "print(exc)",
                                  "logger.warning(exc)", "traceback.print_exc()"])
def test_recording_the_failure_is_accepted(tmp_path, call):
    h = _scan(tmp_path, f"try:\n    x = 1\nexcept Exception as exc:\n    {call}\n")
    assert h[0].verdict == "ok"


def test_a_written_justification_is_accepted(tmp_path):
    """Some handlers return a value describing the failure, which no AST scan
    can see. The rule is to justify it in writing, not to guess at intent."""
    h = _scan(tmp_path,
              "try:\n    x = 1\nexcept Exception:  # handled: returns a Check\n"
              "    return 'failed'\n")
    assert h[0].verdict == "ok" and "justified in writing" in h[0].reason


def test_a_named_exception_needs_nothing(tmp_path):
    h = _scan(tmp_path, "try:\n    x = 1\nexcept ValueError:\n    x = 0\n")
    assert h[0].kind == "specific" and h[0].verdict == "ok"


def test_base_exception_counts_as_broad(tmp_path):
    h = _scan(tmp_path, "try:\n    x = 1\nexcept BaseException:\n    x = 0\n")
    assert h[0].kind == "broad" and h[0].verdict == "violation"


def test_unparseable_files_are_reported_not_skipped(tmp_path):
    h = _scan(tmp_path, "def broken(:\n")
    assert h[0].verdict == "violation" and "parse" in h[0].kind


def test_the_exit_code_drives_ci(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ce, "scan", lambda: [
        ce.Handler("f.py", 1, "broad", "violation", "silent")])
    assert ce.main([]) == 1
    assert "violation" in capsys.readouterr().out

    monkeypatch.setattr(ce, "scan", lambda: [
        ce.Handler("f.py", 1, "specific", "ok", "named")])
    assert ce.main([]) == 0


def test_the_two_dangerous_handlers_now_record():
    """Both silently changed behaviour: one switched the models onto a
    different universe, the other scored a failed measurement as neutral."""
    runner = (ROOT / "sigbot" / "runner.py").read_text()
    assert 'record_skip("board_read"' in runner
    screener = (ROOT / "sigbot" / "screener.py").read_text()
    assert 'record_skip("reactivity"' in screener
