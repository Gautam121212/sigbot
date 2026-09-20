"""Tests for the app data contract.

The point of these is that the interface cannot show a number the backend did
not produce. `test_export_has_no_fabricated_fields` is the one that matters.
"""
from __future__ import annotations

import json

import pytest

from sigbot.export_app import MODEL_META, build_export, write_export
from sigbot.shadow import ShadowLedger
from tests.conftest import write_records


@pytest.fixture
def seeded(tmp_path):
    led = ShadowLedger(tmp_path / "s.db")
    write_records(led, "contagion", "AVGO", 120, 2 / 3)
    # Three paths, not two. `build_export`'s third argument defaults to
    # "watchlist.db" in the current directory, so a two-argument call left a
    # real 100-asset board in the project folder — and `run_screen --apply`
    # then found a full board and discarded the screen result.
    return str(tmp_path / "s.db"), str(tmp_path / "p.db"), str(tmp_path / "w.db")


def _walk_keys(obj):
    """Every key name in a nested structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key).lower()
            yield from _walk_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def test_export_has_no_fabricated_fields(seeded):
    """No portfolio value, no bare 'accuracy' — neither exists in the system.

    Checks key names, not a substring of the serialised blob. The earlier
    version greped the whole JSON for "847", which is three digits that turn up
    inside a microsecond timestamp often enough to fail at random — a test that
    passes most days and fails for no reason is worse than no test, because it
    trains you to re-run rather than read.
    """
    d = build_export(*seeded)
    keys = set(_walk_keys(d))
    for banned in ("portfolio", "portfolio_value", "accuracy"):
        assert banned not in keys, f"fabricated field {banned!r} in the export"

    # The observation count must come from the ledger, never be carried over
    # from a demo fixture.
    assert d["headline"]["observations_total"] == 120, (
        "the headline count does not match what the fixture wrote")


def test_every_model_is_present_even_with_no_data(tmp_path):
    d = build_export(str(tmp_path / "empty.db"), str(tmp_path / "p.db"),
                     str(tmp_path / "w.db"))
    assert {m["id"] for m in d["models"]} == set(MODEL_META)
    for m in d["models"]:
        assert m["resolved"] == 0
        assert m["hit_rate"] is None and m["lower_bound"] is None
        assert m["tier"] == "SILENT"
        assert "Nothing checked yet" in m["status_line"]


def test_headline_says_so_when_nothing_is_proven(tmp_path):
    d = build_export(str(tmp_path / "e.db"), str(tmp_path / "p.db"),
                     str(tmp_path / "w.db"))
    assert d["headline"]["models_alertable"] == 0
    assert "nothing is being made up" in d["headline"]["message"]


def test_real_record_produces_a_tier_and_a_floor(seeded):
    d = build_export(*seeded)
    m = next(x for x in d["models"] if x["id"] == "contagion")
    assert m["resolved"] == 120
    assert 0 < m["lower_bound"] <= m["hit_rate"] <= 1
    assert m["tier"] in ("WATCH", "CAUTION", "TRADE")
    assert m["alerts"] and m["alerts"][0]["symbol"] == "AVGO"


def test_lower_bound_never_exceeds_hit_rate(seeded):
    for m in build_export(*seeded)["models"]:
        if m["hit_rate"] is not None:
            assert m["lower_bound"] <= m["hit_rate"]


def test_disclaimer_is_always_present(seeded, tmp_path):
    empty = (str(tmp_path / "x.db"), str(tmp_path / "y.db"), str(tmp_path / "z.db"))
    for args in (seeded, empty):
        assert "financial advice" in build_export(*args)["disclaimer"]


def test_write_export_produces_loadable_json(seeded, tmp_path):
    out = write_export(tmp_path / "sub" / "data.json", db_path=seeded[0],
                       patterns_path=seeded[1], watchlist_path=seeded[2])
    assert out.exists()
    d = json.loads(out.read_text())
    assert d["generated_at"] and d["models"]


def test_patterns_section_survives_a_missing_registry(tmp_path):
    d = build_export(str(tmp_path / "a.db"), "/nonexistent/dir/p.db",
                     str(tmp_path / "w.db"))
    assert set(d["patterns"]) >= {"discovery", "confirming", "confirmed", "pruned"}


# ------------------------------------------------------- standalone build

def test_standalone_inlines_the_data(tmp_path, seeded):
    """Opened from file://, fetch() is blocked — the data must already be in the page."""
    import json as _json
    import re
    import shutil
    from pathlib import Path

    from sigbot.build_standalone import build_standalone
    from sigbot.export_app import write_export

    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(Path("app/index.html"), app / "index.html")
    write_export(app / "data.json", db_path=seeded[0], patterns_path=seeded[1],
                 watchlist_path=seeded[2])

    out = build_standalone(app)
    html = out.read_text()
    m = re.search(r'<script id="inline-data" type="application/json">(.*?)</script>',
                  html, re.S)
    assert m, "inline slot missing from the built file"
    payload = m.group(1)
    assert "</script>" not in payload, "an unescaped closing tag would break the page"
    data = _json.loads(payload.replace("<\\/", "</"))
    assert data["models"] and data["headline"]
    assert "fetch(" in html, "the served copy must still prefer the live file"


def test_standalone_requires_an_export_first(tmp_path):
    import shutil
    from pathlib import Path

    import pytest as _pytest

    from sigbot.build_standalone import build_standalone

    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(Path("app/index.html"), app / "index.html")
    with _pytest.raises(FileNotFoundError, match="export_app"):
        build_standalone(app)


def test_lan_addresses_excludes_loopback():
    from sigbot.build_standalone import lan_addresses

    assert all(not ip.startswith("127.") for ip in lan_addresses())
