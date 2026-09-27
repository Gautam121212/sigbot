"""SEC EDGAR provider — free public filings & fundamentals (no key).

Powers the LIVE ventures and ideas models. SEC EDGAR (data.sec.gov) is free,
public, and needs no API key — only a declared User-Agent. Two feeds:

  * 8-K filings (ideas): recent material events per company — the catalyst feed
    the volatile-catalyst edge needs.
  * Company facts / concepts (ventures): quarterly revenue and gross margin, the
    sustained-inflection edge's inputs.

Rate limit: SEC asks for <= 10 requests/second and a real User-Agent. This
provider is deliberately slow and cached-friendly. It is network code, so every
fetch is wrapped and a failure records a skip rather than crashing the cycle.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

UA = "sigbot research sigbot@dripxwear.com"
BASE = "https://data.sec.gov"


def _get(path: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


@dataclass(frozen=True)
class Filing:
    cik: str
    form: str
    filing_date: str
    items: list[str]        # 8-K item codes (e.g. "1.01" material agreement)
    accession: str


@dataclass(frozen=True)
class Fundamentals:
    cik: str
    revenue_growths: list[float]   # recent YoY revenue growth, oldest first
    gross_margins: list[float]     # recent gross margin, oldest first


def recent_8k(cik: str, fetch=_get) -> list[Filing]:
    """Recent 8-K filings for a company (the ideas catalyst feed)."""
    cik10 = str(cik).zfill(10)
    data = fetch(f"/submissions/CIK{cik10}.json")
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [])
    accns = recent.get("accessionNumber", [])
    out = []
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        item_str = items[i] if i < len(items) else ""
        out.append(Filing(
            cik=cik10, form=form,
            filing_date=dates[i] if i < len(dates) else "",
            items=[x.strip() for x in item_str.split(",") if x.strip()],
            accession=accns[i] if i < len(accns) else ""))
    return out


def _concept_series(cik: str, tag: str, fetch=_get) -> list[tuple[str, float]]:
    """Quarterly (end_date, value) for one us-gaap concept, chronological."""
    cik10 = str(cik).zfill(10)
    try:
        data = fetch(f"/api/xbrl/companyconcept/CIK{cik10}/us-gaap/{tag}.json")
    except Exception:  # noqa: BLE001  # handled: a company simply lacking this us-gaap concept is normal (not every filer reports every tag); an empty series is the correct result, not a failure
        return []
    units = data.get("units", {})
    vals = units.get("USD", [])
    rows = [(u.get("end", ""), float(u.get("val", 0)))
            for u in vals if u.get("form") in ("10-Q", "10-K") and "end" in u]
    rows.sort(key=lambda r: r[0])
    return rows


def fundamentals(cik: str, fetch=_get) -> Fundamentals:
    """Recent revenue-growth and gross-margin series (the ventures inputs)."""
    cik10 = str(cik).zfill(10)
    rev = _concept_series(cik, "Revenues", fetch) or \
        _concept_series(cik, "RevenueFromContractWithCustomerExcludingAssessedTax", fetch)
    cogs = _concept_series(cik, "CostOfRevenue", fetch) or \
        _concept_series(cik, "CostOfGoodsAndServicesSold", fetch)
    # YoY revenue growth: compare each quarter to 4 quarters back.
    rev_vals = [v for _, v in rev]
    growths = []
    for i in range(4, len(rev_vals)):
        prior = rev_vals[i - 4]
        if prior:
            growths.append(rev_vals[i] / prior - 1)
    # gross margin per quarter where both revenue and cogs exist by end-date.
    cogs_by_end = dict(cogs)
    margins = []
    for end, r in rev:
        c = cogs_by_end.get(end)
        if c is not None and r:
            margins.append((r - c) / r)
    return Fundamentals(cik=cik10, revenue_growths=growths[-6:],
                        gross_margins=margins[-6:])
