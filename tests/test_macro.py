"""The free macro source that feeds venture evidence."""
from __future__ import annotations

import json

from sigbot.macro import evidence_adjustment, read


def _opener(gdp=None, industry=None):
    def open_url(url):
        vals = gdp if "NY.GDP" in url else industry if "NV.IND" in url else []
        if vals is None:
            raise OSError("unreachable")
        return json.dumps([{"page": 1}, [{"value": v} for v in (vals or [])]]).encode()
    return open_url


def test_reads_latest_and_trend():
    r = read("PHL", "gdp_growth", _opener(gdp=[5.2, 4.8, 3.1, 2.9]))
    assert r.ok and r.latest == 5.2 and r.trend == "rising"


def test_a_country_that_cannot_be_read_gets_no_adjustment():
    adj, reasons = evidence_adjustment("ZZZ", _opener(gdp=None, industry=None))
    assert adj == 0.0
    assert any("unavailable" in x for x in reasons)


def test_strong_growth_and_rising_industry_raise_confidence():
    adj, reasons = evidence_adjustment("PHL", _opener(gdp=[5.2, 4.8, 3.0, 2.8],
                                                      industry=[6.0, 5.5, 3.0, 2.8]))
    assert adj > 0
    assert any("GDP" in r for r in reasons)


def test_a_contracting_economy_lowers_confidence():
    adj, _ = evidence_adjustment("XYZ", _opener(gdp=[-2.0, -1.0, 1.0, 2.0],
                                                industry=[-3.0, -2.0, 1.0, 2.0]))
    assert adj < 0


def test_the_adjustment_is_bounded():
    """Macro nudges confidence, never dominates it."""
    adj, _ = evidence_adjustment("PHL", _opener(gdp=[20.0, 18.0, 2.0, 1.0],
                                                industry=[30.0, 25.0, 1.0, 0.5]))
    assert -0.15 <= adj <= 0.15
