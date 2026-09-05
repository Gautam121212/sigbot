"""Which sources the opportunity model reads, and how far to trust each.

The five original feeds were Reuters, WSJ, CNBC, CoinTelegraph and CoinDesk —
two of five crypto, none Indian, none about listings, none about commodities or
property. The venture rubric scores a "supply chain shift" gap type against a
feed set carrying no trade coverage, and the board holds NSE assets while no
Indian outlet was read at all. The model was not restricted by design; it was
restricted by what was plugged in.

## Why RSS and not an API

Every source here is free, keyless, and public. That is not a compromise: the
constraint on the Ideas tab was never article volume, it was which subjects the
sources cover. A paid news API pushing ten times the articles through the same
five outlets gives you more of the same bias.

## Trust is not uniform, and the score says so

`SOURCE_QUALITY` feeds the thesis card's sourcing band. A wire service and an
aggregator that republishes press releases are not equivalent, and treating
them as such is how a promotional listing note becomes a "market thesis".
Anything unlisted defaults to 0.50 — readable, never strong on its own.

Honest constraint: RSS carries headlines and summaries, not filings. An IPO feed
tells you a listing exists, not whether the price is sensible. Nothing here
changes that the opportunity model has no confidence score and cannot have one.

Largest risk: more feeds means more items clearing the relevance filter, and a
busier Ideas tab feels like more opportunity when it is only more input. The
scan already dedupes and only messages what is new; the volume showing up in
the app is the honest count.

Test gap: whether a given feed is alive today is not something a test settles.
`scripts/check_feeds.py` answers that from your machine, and a feed that stops
responding is recorded as a skip rather than quietly dropping out.
"""
from __future__ import annotations

# (url, category, note). Category drives nothing yet beyond reporting — it is
# there so a gap in coverage is visible rather than inferred.
FEED_REGISTRY: list[tuple[str, str, str]] = [
    # ---------------------------------------------------------- global wires
    # Reuters retired its public RSS. Google News still carries the stories and
    # links to reuters.com, so source_quality reads them as Reuters rather than
    # as an unknown aggregator.
    ("https://news.google.com/rss/search?q=when:1d+site:reuters.com+business"
     "&hl=en-US&gl=US&ceid=US:en", "global", "Reuters via Google News"),
    ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "global", "WSJ markets"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "global", "CNBC markets"),
    ("https://feeds.marketwatch.com/marketwatch/topstories/", "global", "MarketWatch"),

    # ------------------------------------------------------------- India
    # The board holds NSE assets and none of these were being read.
    ("https://economictimes.indiatimes.com/rssfeedstopstories.cms", "india",
     "Economic Times top stories"),
    ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "india",
     "Economic Times markets"),
    ("https://www.business-standard.com/rss/markets-106.rss", "india",
     "Business Standard markets"),
    ("https://www.business-standard.com/rss/companies-101.rss", "india",
     "Business Standard companies"),
    ("https://www.livemint.com/rss/markets", "india", "Mint markets"),
    ("https://www.livemint.com/rss/companies", "india", "Mint companies"),
    # Moneycontrol answers 403 to anything that is not a browser, on every
    # one of its feeds. Reached the same way.
    ("https://news.google.com/rss/search?q=when:1d+site:moneycontrol.com"
     "&hl=en-IN&gl=IN&ceid=IN:en", "india", "Moneycontrol via Google News"),
    ("https://www.financialexpress.com/market/feed/", "india",
     "Financial Express markets"),
    ("https://www.thehindubusinessline.com/markets/feeder/default.rss", "india",
     "Hindu BusinessLine markets"),

    # ------------------------------------------------------------- listings
    # A listing reaches you here directly rather than only if a markets desk
    # happens to write about it.
    ("https://news.google.com/rss/search?q=when:2d+India+IPO+listing+subscription"
     "&hl=en-IN&gl=IN&ceid=IN:en", "listings", "India IPOs via Google News"),
    ("https://economictimes.indiatimes.com/markets/ipos/fpos/rssfeeds/14655708.cms",
     "listings", "Economic Times IPOs"),
    ("https://www.business-standard.com/rss/markets/ipo-10618.rss", "listings",
     "Business Standard IPOs"),
    ("https://www.nasdaq.com/feed/rssoutbound?category=IPOs", "listings",
     "Nasdaq IPO calendar"),

    # -------------------------------------------------------- commodities
    # "Supply chain shift" and "price dislocation" are gap types the rubric
    # scores. Without these it was scoring a category it could not observe.
    ("https://www.mining.com/feed/", "commodities", "Mining.com"),
    ("https://oilprice.com/rss/main", "commodities", "OilPrice"),
    # Agriculture.com moved and S&P blocks non-browsers. Topic searches cover
    # the same ground without depending on one publisher staying reachable.
    ("https://news.google.com/rss/search?q=when:2d+(wheat+OR+corn+OR+soybean)"
     "+prices+supply&hl=en-US&gl=US&ceid=US:en", "commodities",
     "Agricultural commodities via Google News"),
    ("https://news.google.com/rss/search?q=when:2d+(copper+OR+lithium+OR+nickel"
     "+OR+cobalt)+price+supply&hl=en-US&gl=US&ceid=US:en", "commodities",
     "Industrial metals via Google News"),

    # -------------------------------------------------------- energy and EV
    ("https://cleantechnica.com/feed/", "energy", "CleanTechnica"),
    ("https://electrek.co/feed/", "energy", "Electrek"),
    ("https://www.utilitydive.com/feeds/news/", "energy", "Utility Dive"),

    # ------------------------------------------------------------- property
    ("https://news.google.com/rss/search?q=when:2d+India+real+estate+property"
     "+prices&hl=en-IN&gl=IN&ceid=IN:en", "property",
     "India property via Google News"),
    ("https://news.google.com/rss/search?q=when:2d+global+property+market+prices"
     "&hl=en-US&gl=US&ceid=US:en", "property", "Global property via Google News"),
    ("https://economictimes.indiatimes.com/industry/services/property-/-cstruction/"
     "rssfeeds/13358050.cms", "property", "Economic Times property"),

    # ----------------------------------------------------------- regulation
    # A rule change is a gap type. It used to reach the model second-hand.
    ("https://www.federalregister.gov/api/v1/documents.rss?conditions%5Btype%5D"
     "%5B%5D=RULE", "regulation", "US Federal Register rules"),
    ("https://ustr.gov/rss.xml", "regulation", "US Trade Representative"),

    # ------------------------------------------------------- supply chain
    ("https://www.supplychaindive.com/feeds/news/", "supply_chain",
     "Supply Chain Dive"),
    ("https://www.freightwaves.com/news/feed", "supply_chain", "FreightWaves"),

    # ------------------------------------------------------------ research
    # Primary sources and working papers. Slow-moving and rarely urgent, which
    # is the point: a regulator's own announcement is the thing the trade press
    # reports a day later, and a working paper is where an idea appears before
    # anyone is trading it. Neither is a signal — both are context the news
    # feeds do not carry.
    ("https://www.rbi.org.in/Scripts/Rss.aspx", "research",
     "Reserve Bank of India"),
    ("https://www.sebi.gov.in/sebirss.xml", "research", "SEBI announcements"),
    ("https://export.arxiv.org/rss/q-fin", "research", "arXiv quantitative finance"),
    ("https://export.arxiv.org/rss/econ", "research", "arXiv economics"),
    ("https://www.nber.org/rss/new.xml", "research", "NBER working papers"),
    ("https://www.bis.org/doclist/all_rss.xml", "research",
     "Bank for International Settlements"),

    # --------------------------------------------------------------- crypto
    ("https://cointelegraph.com/rss", "crypto", "CoinTelegraph"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto", "CoinDesk"),
]

DEFAULT_FEEDS = [url for url, _cat, _note in FEED_REGISTRY]

# How far to trust each outlet. A wire service and an aggregator republishing
# press releases are not equivalent, and scoring them alike is how a
# promotional listing note becomes a "market thesis".
SOURCE_QUALITY = {
    # Wires and papers of record. `dj` is the WSJ feed host; bloomberg and ft
    # are kept because their stories reach the model as citations inside other
    # outlets' articles, and a citation to a wire should not be scored as an
    # unknown source. Neither publishes a usable free feed.
    # spglobal and agriculture kept: both blocked their own feeds, but their
    # stories still arrive as links inside the Google News topic searches, and
    # a link to S&P should not score as an unknown outlet.
    "reuters": 1.00, "dj": 0.95, "wsj": 0.95, "bloomberg": 0.95, "ft": 0.92,
    "spglobal": 0.90, "agriculture": 0.62,
    "federalregister": 0.95, "ustr": 0.90,
    # established business press
    "cnbc": 0.80, "marketwatch": 0.75,
    "economictimes": 0.78, "business-standard": 0.78, "livemint": 0.78,
    "thehindubusinessline": 0.75,
    # trade press: good on their beat, narrow outside it
    "supplychaindive": 0.72, "freightwaves": 0.70, "utilitydive": 0.72,
    "mining": 0.68, "oilprice": 0.60,
    "electrek": 0.60, "cleantechnica": 0.55,
    # aggregators and outlets that carry a lot of unfiltered releases
    "moneycontrol": 0.65, "nasdaq": 0.65, "financialexpress": 0.70,
    # Primary sources: a regulator publishing its own decision is as close to
    # the fact as it is possible to get. Working papers are peer-reviewed or
    # institutionally backed, which is not the same as correct, but is a long
    # way above an outlet with no editorial record.
    "rbi.org": 0.95, "sebi.gov": 0.95, "bis.org": 0.90, "nber.org": 0.85,
    "arxiv": 0.70,
    # Google News itself is never the source. Its items carry a link to the
    # outlet that reported the story, and source_quality reads that instead.
    # An item whose link resolves to nothing known lands on DEFAULT_QUALITY,
    # which is readable and never strong on its own.
    "news.google": 0.40,
    "coindesk": 0.70, "cointelegraph": 0.55,
}

# Below the venture scanner's 0.5 floor, deliberately. Raising this to 0.50
# let an unrecognised blog clear that filter at exactly the threshold, which
# is how "reporting points to a copper shortage" ends up sourced to
# randomblog.xyz. An unknown outlet is readable context, never a candidate on
# its own.
DEFAULT_QUALITY = 0.40


def categories() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for url, category, _note in FEED_REGISTRY:
        out.setdefault(category, []).append(url)
    return out


def describe() -> str:
    groups = categories()
    lines = [f"{len(FEED_REGISTRY)} feeds across {len(groups)} categories:"]
    for category, urls in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {category:<14} {len(urls)}")
    lines.append("\nA category with feeds is not a category with coverage — "
                 "run scripts/check_feeds.py to see which actually respond "
                 "from this machine.")
    return "\n".join(lines)
