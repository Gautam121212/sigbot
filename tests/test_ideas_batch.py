"""The three suggested changes plus the horizon measurement."""
from __future__ import annotations


def test_contagion_records_every_trigger_not_only_alertable_ones():
    """Recording and alerting were one decision, so a link that failed the
    alert bar was never written down — and the model finished its first month
    with ONE resolved check out of 17,583 firings. It could not learn because
    it refused to observe."""
    import inspect

    import sigbot.runner as runner

    src = inspect.getsource(runner.run_contagion)
    record_at = src.index('ledger.record("contagion"')
    skip_at = src.index("if not ok:")
    assert record_at < skip_at, (
        "the prediction must be recorded before the alert gate can skip it")


def test_the_alert_gate_is_still_strict():
    """A permissive recording gate must not become a permissive alert gate.
    Observing costs nothing; acting does."""
    from sigbot.contagion import ContagionGates

    gates = ContagionGates()
    assert gates.min_hit_lower_over_base >= 0.05
    assert gates.min_edge_over_base >= 0.03
    assert gates.min_events >= 30


def test_every_model_has_a_fixed_sample_target():
    """Watching a growing sample against a threshold is the
    multiple-comparisons problem: peek often enough and any bar is crossed by
    luck. A target set in advance fixes the judging point."""
    from sigbot.export_app import MODEL_META, TARGET_CHECKS

    for model_id in MODEL_META:
        assert TARGET_CHECKS.get(model_id, 0) >= 100, model_id


def test_the_benchmark_wording_does_not_conclude_early(tmp_path):
    from sigbot.export_app import build_export

    data = build_export(str(tmp_path / "a.db"), str(tmp_path / "b.db"),
                        str(tmp_path / "c.db"))
    for m in data["models"]:
        if m["resolved"] < m["target_checks"]:
            assert "Nothing is concluded" in m["benchmark"], m["id"]


def test_the_horizon_job_measures_the_ceiling_not_the_model():
    """A move under the cost bar is a miss however well it was called, so the
    winnable share IS the hit-rate ceiling. Reporting it as model quality
    would be a category error."""
    import inspect

    import sigbot.runner as runner

    src = inspect.getsource(runner.run_horizons)
    assert "perfect forecaster" in src
    assert "does not create an edge" in src


def test_generated_files_are_not_tracked():
    """Each is rebuilt from the ledger on every run, on two machines. Tracking
    them asks git to merge two renderings of identical data, which conflicted
    on every pull and broke four consecutive ships."""
    from pathlib import Path

    ignored = (Path(__file__).resolve().parents[1] / ".gitignore").read_text()
    for generated in ("app/data.json", "app/public/", "app/sigbot-report.html",
                      "outbox.log"):
        assert generated in ignored, f"{generated} must not be tracked"
    # The ledger must still be force-added by the ship script.
    ship = (Path(__file__).resolve().parents[1] / "scripts" / "ship.sh").read_text()
    assert "shadow.db" in ship and 'git add -f "$f"' in ship


class _settings_at:
    """Settings pointing at a specific database file.

    NOT `type(SETTINGS)()`. A dataclass field default like
    `os.environ.get("SIGBOT_DB", "shadow.db")` is evaluated once when the
    class is created, so a monkeypatched env var never reaches a freshly
    constructed instance — and an earlier version of these tests deleted the
    real ledger because of exactly that.
    """

    def __init__(self, path):
        self.shadow_db = str(path)


def test_reset_keeps_correctly_scored_rows(tmp_path):
    """A record collected under a mis-set gate is not contaminated. The hit
    definition never changed and the prices are real — what was wrong was the
    bar, applied at read time. Deleting valid evidence to fix a number that is
    already fixed is a bad trade."""
    import sigbot.runner as runner
    from sigbot.shadow import ShadowLedger

    settings = _settings_at(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)

    keep = ledger.record("daily", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(keep, 104.0)
    drop = ledger.record("daily", "BTC-USD", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(drop, 104.0)

    runner.run_reset(settings=settings)

    import sqlite3
    con = sqlite3.connect(settings.shadow_db)
    symbols = {r[0] for r in con.execute("SELECT symbol FROM predictions")}
    assert "AAPL" in symbols, "valid stock evidence must survive"
    assert "BTC-USD" not in symbols, "daily never should have forecast crypto"


def test_reset_all_clears_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGBOT_CONFIRM_RESET", "yes")
    import sqlite3

    import sigbot.runner as runner
    from sigbot.shadow import ShadowLedger

    settings = _settings_at(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    pid = ledger.record("news", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(pid, 104.0)

    runner.run_reset(settings=settings, full=True)
    con = sqlite3.connect(settings.shadow_db)
    assert con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_a_full_wipe_refuses_without_explicit_confirmation(tmp_path,
                                                           monkeypatch, capsys):
    """A full wipe destroys weeks of evidence that cannot be recreated, so it
    must not happen on a typo or a stray test."""
    import sigbot.runner as runner
    from sigbot.shadow import ShadowLedger

    monkeypatch.delenv("SIGBOT_CONFIRM_RESET", raising=False)
    settings = _settings_at(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    pid = ledger.record("news", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(pid, 104.0)

    runner.run_reset(settings=settings, full=True)
    assert "Refusing to wipe" in capsys.readouterr().out

    import sqlite3
    con = sqlite3.connect(settings.shadow_db)
    assert con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1


def test_reset_snapshots_before_deleting(tmp_path):
    """Cheap insurance against the accident that wiped the ledger once."""
    import sigbot.runner as runner
    from sigbot.shadow import ShadowLedger

    settings = _settings_at(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    pid = ledger.record("daily", "BTC-USD", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(pid, 104.0)

    runner.run_reset(settings=settings)
    assert list(tmp_path.glob("*.bak")), "a snapshot must exist before deletion"
