#!/usr/bin/env python3
"""Data-connectivity diagnostic — DOES NOTHING but probe reachability.

No strategy, no model, no order, no database write. It answers one question for
whatever environment it runs in (GitHub Actions, a Mac, a sandbox): can the data
hosts the models depend on actually be reached from here? Prints one line per
host and a summary. Always exits 0 — it must never fail or hang a build
(per-host timeout 8s).
"""
from __future__ import annotations

import socket
import ssl
import sys
import urllib.error
import urllib.request

UA = "sigbot-netcheck/1.0 (diagnostic; sigbot@dripxwear.com)"

PROBES = [
    ("yahoo-q1   (stocks/crypto)", "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d"),
    ("yahoo-q2   (stocks/crypto)", "https://query2.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d"),
    ("binance    (crypto)",        "https://api.binance.com/api/v3/ping"),
    ("coingecko  (crypto)",        "https://api.coingecko.com/api/v3/ping"),
    ("sec-edgar  (ventures/ideas)","https://data.sec.gov/submissions/CIK0000320193.json"),
    ("gdelt      (news-health)",   "https://api.gdeltproject.org/api/v2/doc/doc?query=apple&mode=artlist&maxrecords=1&format=json"),
    ("google-rss (news)",          "https://news.google.com/rss/search?q=apple"),
]


def probe(url: str, timeout: float = 8.0) -> tuple[str, str]:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return ("REACHABLE", f"HTTP {r.status}")
    except urllib.error.HTTPError as e:
        return ("REACHABLE", f"HTTP {e.code}")
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as e:
        reason = getattr(e, "reason", e)
        return ("BLOCKED", f"{type(e).__name__}: {str(reason)[:80]}")


def main() -> int:
    print("=" * 64)
    print("SIGBOT DATA-CONNECTIVITY CHECK  (diagnostic only - no trading)")
    print("=" * 64)
    reachable = 0
    for label, url in PROBES:
        verdict, detail = probe(url)
        mark = "OK  " if verdict == "REACHABLE" else "FAIL"
        if verdict == "REACHABLE":
            reachable += 1
        print(f"  [{mark}] {label:30} {verdict:10} {detail}")
    print("-" * 64)
    print(f"  {reachable}/{len(PROBES)} data hosts reachable from this environment.")
    if reachable == 0:
        print("  VERDICT: no market data reachable here - models cannot produce.")
    elif reachable < len(PROBES):
        print("  VERDICT: partial - some families can run, others are blocked.")
    else:
        print("  VERDICT: all probed hosts reachable.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
