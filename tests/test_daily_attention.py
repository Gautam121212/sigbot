"""The daily attention rollup stays bounded — one row per day, forever."""
from __future__ import annotations

import json
from datetime import datetime


class _Article:
    def __init__(self, day):
        self.published_at = datetime.fromisoformat(day + "T10:00:00+00:00")
        self.title = "x"
        self.url = f"http://x/{day}"
        self.source = "s"


def test_daily_rollup_is_one_row_per_day(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    # Two days of articles, many each.
    arts = [_Article("2026-09-24") for _ in range(500)]
    arts += [_Article("2026-09-25") for _ in range(800)]
    runner._update_daily_attention(arts, ["DROP"] * len(arts))
    rows = [json.loads(x) for x in
            (tmp_path / "news_daily.jsonl").read_text().splitlines() if x.strip()]
    assert len(rows) == 2, "one row per calendar day, not per article"
    by_day = {r["date"]: r["count"] for r in rows}
    assert by_day["2026-09-24"] == 500 and by_day["2026-09-25"] == 800


def test_rollup_accumulates_across_runs(tmp_path, monkeypatch):
    import sigbot.runner as runner
    monkeypatch.chdir(tmp_path)
    runner._update_daily_attention([_Article("2026-09-25") for _ in range(100)],
                                   ["DROP"] * 100)
    runner._update_daily_attention([_Article("2026-09-25") for _ in range(50)],
                                   ["DROP"] * 50)
    rows = [json.loads(x) for x in
            (tmp_path / "news_daily.jsonl").read_text().splitlines() if x.strip()]
    assert len(rows) == 1
    assert rows[0]["count"] == 150, "same day accumulates, file stays one row"
