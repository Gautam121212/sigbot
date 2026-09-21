"""GDELT through its bulk files — the fix for the refused search API."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone

from sigbot.providers.gkg import GKGProvider, parse_rows, quarter_stamps


def _row(url="https://reuters.com/x", title="Nvidia beats estimates",
         date="20260921120000", source="reuters.com", orgs="nvidia,12;apple,40",
         tone="3.2,5,1.8,6.8,20,0,500"):
    cols = [""] * 27
    cols[0], cols[1], cols[3], cols[4] = "20260921120000-1", date, source, url
    cols[14], cols[15] = orgs, tone
    cols[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE><PAGE_AUTHORS>x</PAGE_AUTHORS>"
    return "\t".join(cols)


def _zip(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20260921120000.gkg.csv", text)
    return buf.getvalue()


SINCE = datetime(2026, 9, 21, tzinfo=timezone.utc)


def test_parses_title_url_source_orgs_and_tone():
    arts = parse_rows(_row(), SINCE)
    assert len(arts) == 1
    a = arts[0]
    assert a.title == "Nvidia beats estimates" and a.source == "reuters.com"
    assert "nvidia" in a.summary and "tone: 3.2" in a.summary
    assert a.published_at == datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def test_rows_without_a_title_or_too_old_or_malformed_are_skipped():
    rows = "\n".join([_row(title=""), _row(date="20250101000000"), "a\tb\tc",
                      _row(url="not-a-url")])
    assert parse_rows(rows, SINCE) == []


def test_file_stamps_are_quarter_hours_newest_first_and_skip_the_unpublished():
    now = datetime(2026, 9, 21, 12, 7, tzinfo=timezone.utc)
    stamps = quarter_stamps(now - timedelta(hours=1), now)
    assert stamps[0] == "20260921114500", "the 12:00 file is not out yet"
    assert all(s[-4:] in ("0000", "1500", "3000", "4500") for s in stamps)
    assert stamps == sorted(stamps, reverse=True)


def test_each_file_is_read_once_across_runs(tmp_path):
    fetched = []

    def fake(url):
        fetched.append(url)
        return _zip(_row(date=url.rsplit("/", 1)[1][:14]))

    state = str(tmp_path / "state.json")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    first = GKGProvider(fetch_bytes=fake, state_file=state).fetch(since)
    n = len(fetched)
    second = GKGProvider(fetch_bytes=fake, state_file=state).fetch(since)
    assert first and n > 0
    assert len(fetched) == n and second == [], "no file is downloaded twice"


def test_a_missing_file_does_not_stop_the_rest(tmp_path):
    def flaky(url):
        if url.endswith("1500.gkg.csv.zip"):
            raise OSError("404")
        return _zip(_row(date=url.rsplit("/", 1)[1][:14]))

    since = datetime.now(timezone.utc) - timedelta(hours=2)
    out = GKGProvider(fetch_bytes=flaky, state_file=str(tmp_path / "s.json")).fetch(since)
    assert out, "the other files still arrive"


def test_news_uses_the_bulk_files_not_the_refused_api():
    import inspect

    import sigbot.runner as runner
    src = inspect.getsource(runner._news_provider)
    assert "GKGProvider()" in src and "GDELTProvider()" not in src
