"""Discovery framework: try everything, label risky, reject corruption."""
from __future__ import annotations

from sigbot.discovery import Discovery, register


def test_a_flipping_signal_is_discarded():
    d = Discovery("x", "ledger", "thesis", half1=-1.5, half2=0.5)
    assert d.verdict == "DISCARD"
    assert not d.survives_out_of_sample


def test_a_consistent_small_signal_is_risky_kept(tmp_path):
    d = Discovery("y", "news", "thesis", half1=0.6, half2=0.9)
    assert d.verdict == "RISKY-KEEP"
    out = register(d, path=str(tmp_path / "r.jsonl"))
    assert "RISKY-KEEP" in out and "risky loop" in out


def test_corruption_sized_effect_is_rejected(tmp_path):
    """The +28,000% small-cap 'edge' must be caught as bad data, not filed."""
    d = Discovery("z", "coingecko", "thesis", half1=46834.0, half2=111910.0)
    assert d.is_corruption
    assert d.verdict == "CORRUPT-DATA"
    out = register(d, path=str(tmp_path / "r.jsonl"))
    assert "CORRUPT-DATA" in out
    # and nothing was filed
    assert not (tmp_path / "r.jsonl").exists() or \
        "z" not in (tmp_path / "r.jsonl").read_text()


def test_a_trivial_signal_is_discarded():
    d = Discovery("t", "ledger", "thesis", half1=0.1, half2=0.1)
    assert not d.survives_out_of_sample     # below the 0.3 floor
