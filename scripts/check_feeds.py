#!/usr/bin/env python3
"""Which feeds actually respond from this machine.

I could not test these myself: this sandbox allows a short list of domains and
every one of them returned 403 regardless of whether it works for you. So the
list in feeds.py is curated, not verified — a URL that looks right and 404s is
indistinguishable from a working one until something fetches it.

Run it here and on the server. The answers differ: some outlets serve RSS to
residential addresses and block datacenters, which is the same asymmetry that
makes Yahoo behave differently on Oracle.

    python scripts/check_feeds.py            check every feed
    python scripts/check_feeds.py --prune    print a list with the dead ones
                                             removed, to paste into feeds.py
"""
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigbot.providers.feeds import FEED_REGISTRY  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
TIMEOUT = 20


def check(url: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001  # handled: the failure is the result — this script reports which feeds answer
        return False, type(exc).__name__

    # A 200 proves the server answered, not that it answered with a feed.
    # Stooq taught us that: it returns 200 with an HTML block page, which at
    # the HTTP level is indistinguishable from success.
    lowered = body.lower()
    if "<rss" in lowered or "<feed" in lowered or "<rdf" in lowered:
        items = lowered.count("<item") + lowered.count("<entry")
        return True, f"{items} item(s) in first 4KB"
    if "<html" in lowered:
        return False, "HTML, not a feed"
    return False, "unrecognised body"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    results: list[tuple[str, str, str, bool, str]] = []

    print(f"Checking {len(FEED_REGISTRY)} feeds...\n")
    for url, category, note in FEED_REGISTRY:
        ok, detail = check(url)
        results.append((url, category, note, ok, detail))
        print(f"  {'ok  ' if ok else 'DEAD'}  {note:<34} {detail}")

    by_category: dict[str, list[bool]] = defaultdict(list)
    for _u, category, _n, ok, _d in results:
        by_category[category].append(ok)

    print("\nCoverage by category:")
    empty = []
    for category, flags in sorted(by_category.items()):
        live = sum(flags)
        print(f"  {category:<14} {live}/{len(flags)}")
        if live == 0:
            empty.append(category)

    live = sum(1 for *_x, ok, _d in results if ok)
    print(f"\n{live} of {len(results)} feeds are alive.")
    if empty:
        print(f"\nNo working source for: {', '.join(empty)}.")
        print("The opportunity model scores gap types it now cannot observe in "
              "those areas — it will simply never raise one, which reads as "
              "'nothing happened' rather than 'nobody was looking'.")

    if "--prune" in argv:
        print("\n--- feeds.py list with the dead ones removed ---")
        for url, category, note, ok, _d in results:
            if ok:
                print(f'    ("{url}", "{category}", "{note}"),')
    else:
        print("\nRe-run with --prune to print a list without the dead feeds.")
    return 0 if live else 1


if __name__ == "__main__":
    raise SystemExit(main())
