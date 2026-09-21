"""GDELT: global news, keyless, with a searchable recent archive.

Taken from OSIRIS's source list (MIT licensed) rather than running OSIRIS
itself. OSIRIS's own "news" layer is 23 live video streams, which sigbot
cannot read; GDELT is the part of its stack that is text, timestamped, and
searchable — which is what the news model needs.

What it adds over the RSS feeds:
  * breadth — articles from sources worldwide, not a fixed list of 39 feeds;
  * a searchable window of about three months, so headlines can be matched to
    what prices did afterwards. The deep archive (2015 onward, as bulk files)
    is a separate, larger project.

Queries are grouped by the event classes the intake gate treats as material,
so GDELT is asked for what could matter rather than for everything.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..skips import record_skip
from ..types import Article

API = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT asks for no more than one request every five seconds.
PAUSE_SECONDS = 5.0
TIMEOUT = 20.0
MAX_RECORDS = 250

QUERIES = (
    '(earnings OR guidance OR "quarterly results" OR "profit warning") sourcelang:english',
    '(merger OR acquisition OR takeover OR buyout OR IPO) sourcelang:english',
    '(bankruptcy OR default OR downgrade OR "rating cut") sourcelang:english',
    '("interest rate" OR "central bank" OR tariff OR sanctions) sourcelang:english',
    '(OPEC OR crude OR Hormuz OR "Red Sea" OR pipeline OR refinery) sourcelang:english',
)


def _seen(stamp: str) -> datetime | None:
    """GDELT's seendate, e.g. 20260921T123000Z."""
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def parse(payload: dict, since: datetime) -> list[Article]:
    """Articles from one GDELT response, newer than `since`."""
    now = datetime.now(timezone.utc)
    out = []
    for a in payload.get("articles") or []:
        ts = _seen(a.get("seendate", ""))
        url, title = a.get("url") or "", (a.get("title") or "").strip()
        if not ts or ts < since or not url or not title:
            continue
        out.append(Article(
            uid=hashlib.sha256(f"{url}|{title}".encode()).hexdigest()[:16],
            title=title,
            summary="",
            url=url,
            source=a.get("domain") or "GDELT",
            published_at=ts,
            ingested_at=now,
        ))
    return out


class GDELTProvider:
    def __init__(self, queries=QUERIES, pause: float = PAUSE_SECONDS):
        self.queries = list(queries)
        self.pause = pause

    def fetch(self, since: datetime) -> list[Article]:
        hours = max(1, int((datetime.now(timezone.utc) - since).total_seconds() // 3600) + 1)
        seen: set[str] = set()
        out: list[Article] = []
        for i, q in enumerate(self.queries):
            if i and self.pause:
                time.sleep(self.pause)
            params = urllib.parse.urlencode({
                "query": q, "mode": "ArtList", "format": "json",
                "maxrecords": MAX_RECORDS, "timespan": f"{min(hours, 24 * 90)}h",
                "sort": "DateDesc"})
            try:
                req = urllib.request.Request(f"{API}?{params}",
                                             headers={"User-Agent": "sigbot/1.0"})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            except Exception as exc:  # noqa: BLE001  # handled: recorded; the RSS feeds still run
                # Stop at the FIRST refusal. GDELT throttles far harder than
                # its documented one-request-per-five-seconds — measured
                # refusing even widely spaced requests from ordinary
                # connections — so after one 429 the rest of the run's queries
                # would be refused too, spending minutes for nothing.
                record_skip("gdelt", q[:40], exc)
                break
            for art in parse(payload, since):
                if art.url not in seen:
                    seen.add(art.url)
                    out.append(art)
        return out


class CombinedNewsProvider:
    """RSS feeds plus GDELT, de-duplicated by link.

    Either source failing leaves the other working: the RSS feeds were the
    whole news model before GDELT and must not depend on it.
    """

    def __init__(self, providers):
        self.providers = list(providers)

    def fetch(self, since: datetime) -> list[Article]:
        seen: set[str] = set()
        out: list[Article] = []
        for p in self.providers:
            try:
                arts = p.fetch(since)
            except Exception as exc:  # noqa: BLE001  # handled: recorded; the other sources still run
                record_skip("news_sources", type(p).__name__, exc)
                continue
            for a in arts:
                key = a.url or a.uid
                if key not in seen:
                    seen.add(key)
                    out.append(a)
        return out
