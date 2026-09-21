"""GDELT's bulk news files — the fix for GDELT refusing every API request.

GDELT's search API refused every request we made, from several networks, and
its own refusal message tells heavy users to switch to its bulk datasets. The
Global Knowledge Graph (GKG) is published as a plain file every fifteen
minutes at a predictable address:

    http://data.gdeltproject.org/gdeltv2/YYYYMMDDHHMMSS.gkg.csv.zip

These are static downloads, not a rate-limited API, and the same address
pattern reaches back to 2015 — so this is also the route to a full news
archive, not just the last three months.

Each row is one article: its URL, source site, the organisations it names, a
tone score, and (in the extras field) the page title. Rows without a title are
skipped — the intake gate judges titles.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..skips import record_skip
from ..types import Article

BASE = "http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"
STATE_FILE = "gkg_state.json"

# Files per run. News runs every three hours = twelve quarter-hours; files
# are ~12 MB zipped, so a run downloads at most ~150 MB and only files it has
# not already read.
MAX_FILES = 12
MAX_BYTES = 80_000_000
TIMEOUT = 60.0
MAX_ROWS_PER_FILE = 20_000

_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.DOTALL)


def quarter_stamps(since: datetime, now: datetime, limit: int = MAX_FILES) -> list[str]:
    """GKG file stamps between `since` and now, newest first.

    Files appear a few minutes after each quarter-hour, so the current one is
    skipped: asking for it early is a guaranteed 404.
    """
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=20)
    end = end - timedelta(minutes=end.minute % 15)
    out: list[str] = []
    t = end
    while t > since and len(out) < limit:
        out.append(t.strftime("%Y%m%d%H%M%S"))
        t -= timedelta(minutes=15)
    return out


def parse_rows(text: str, since: datetime, limit: int = MAX_ROWS_PER_FILE) -> list[Article]:
    """Articles from the tab-separated GKG 2.1 rows of one file."""
    now = datetime.now(timezone.utc)
    out: list[Article] = []
    for line in text.splitlines()[:limit]:
        cols = line.split("\t")
        if len(cols) < 27:
            continue
        m = _TITLE.search(cols[26])
        url = cols[4].strip()
        if not m or not url.startswith("http"):
            continue
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        try:
            ts = datetime.strptime(cols[1], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts < since or not title:
            continue
        tone = cols[15].split(",")[0] if cols[15] else ""
        orgs = ";".join(o.split(",")[0] for o in cols[14].split(";") if o)[:300]
        out.append(Article(
            uid=hashlib.sha256(f"{url}|{title}".encode()).hexdigest()[:16],
            title=title[:300],
            summary=f"orgs: {orgs} | tone: {tone}",
            url=url,
            source=cols[3] or "GDELT",
            published_at=ts,
            ingested_at=now,
        ))
    return out


class GKGProvider:
    def __init__(self, fetch_bytes=None, state_file: str = STATE_FILE):
        self._fetch = fetch_bytes or self._download
        self.state_file = state_file

    @staticmethod
    def _download(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "sigbot/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(MAX_BYTES)

    def _last_read(self) -> str:
        try:
            return json.loads(Path(self.state_file).read_text()).get("last", "")
        except (OSError, ValueError):
            return ""

    def fetch(self, since: datetime) -> list[Article]:
        now = datetime.now(timezone.utc)
        last = self._last_read()
        stamps = [s for s in quarter_stamps(since, now) if s > last]
        out: list[Article] = []
        newest = last
        for stamp in stamps:
            url = BASE.format(stamp=stamp)
            try:
                raw = self._fetch(url)
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    name = z.namelist()[0]
                    text = z.read(name).decode("utf-8", "replace")
            except Exception as exc:  # noqa: BLE001  # handled: one missing file must not stop the others
                record_skip("gkg", stamp, exc)
                continue
            out.extend(parse_rows(text, since))
            newest = max(newest, stamp)
        if newest != last:
            try:
                Path(self.state_file).write_text(json.dumps({"last": newest}))
            except OSError as exc:
                record_skip("gkg", "state", exc)
        return out
