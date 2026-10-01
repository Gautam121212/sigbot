"""Strategy distillation — extract capability, NO_SPECIALIST by default."""
from sigbot.strategy_distillation import (
    DistillationLedger, DistillationVerdict, FlawType,
    StrategyDistiller)


def _d():
    return StrategyDistiller()


def _cap(d, sid="S"):
    return d.extract_capability(sid, "mechanism", ("price",), ("scn1",))


# ── capability extraction is a hypothesis, not a claim ──────────────────────
def test_extract_capability_names_mechanism():
    cap = _d().extract_capability("BreakoutBot", "vol expansion breakout",
                                  ("price", "volume", "ATR"), ("vol_contraction",))
    assert cap.mechanism == "vol expansion breakout"
    assert "price" in cap.dependencies


# ── the key verdict: edge was really the flaw ───────────────────────────────
def test_capability_was_the_flaw():
    """+12% backtest collapses to -0.8% once flaws stripped = the flaw WAS the edge."""
    d = _d()
    r = d.distill("S", _cap(d), d.inventory_flaws((FlawType.SMALLCAP_EXPOSURE,)),
                  edge_before=12.0, edge_after=-0.8, surviving_scenarios=())
    assert r.verdict == DistillationVerdict.CAPABILITY_WAS_THE_FLAW
    assert not r.capability_survived_flaw_removal()


# ── a real capability survives ──────────────────────────────────────────────
def test_validated_specialist_when_edge_survives():
    d = _d()
    r = d.distill("S", _cap(d), d.inventory_flaws((FlawType.NO_LIQUIDITY_CAP,)),
                  edge_before=8.0, edge_after=2.1, surviving_scenarios=("vol_contraction",))
    assert r.verdict == DistillationVerdict.VALIDATED_SPECIALIST
    assert r.capability_survived_flaw_removal()


# ── no surviving scenario -> no specialist ──────────────────────────────────
def test_no_specialist_when_no_scenario_survives():
    d = _d()
    r = d.distill("S", _cap(d), d.inventory_flaws((FlawType.FIXED_STOP,)),
                  edge_before=5.0, edge_after=0.3, surviving_scenarios=())
    assert r.verdict == DistillationVerdict.NO_SPECIALIST


# ── no_specialist is the default output ─────────────────────────────────────
def test_no_specialist_is_default_for_zero_edge():
    d = _d()
    r = d.distill("S", _cap(d), d.inventory_flaws(()),
                  edge_before=0.0, edge_after=0.0, surviving_scenarios=())
    assert r.verdict == DistillationVerdict.NO_SPECIALIST


# ── ledger keeps failures and reports a low survival rate ───────────────────
def test_ledger_tracks_all_verdict_types():
    d = _d()
    led = DistillationLedger()
    led.append(d.distill("A", _cap(d, "A"), d.inventory_flaws((FlawType.SMALLCAP_EXPOSURE,)),
                         12.0, -0.8, ()))                      # flaw
    led.append(d.distill("B", _cap(d, "B"), d.inventory_flaws(()),
                         8.0, 2.1, ("scn1",)))                 # specialist
    led.append(d.distill("C", _cap(d, "C"), d.inventory_flaws(()),
                         5.0, 0.3, ()))                        # no specialist
    assert len(led.all()) == 3
    assert len(led.validated_specialists()) == 1
    assert len(led.capability_was_flaw()) == 1
    assert len(led.no_specialist()) == 1


def test_survival_rate_is_low_and_reported():
    d = _d()
    led = DistillationLedger()
    # 1 survivor out of 4 = 25%
    led.append(d.distill("A", _cap(d, "A"), d.inventory_flaws(()), 8.0, 2.0, ("scn1",)))
    for sid in ("B", "C", "D"):
        led.append(d.distill(sid, _cap(d, sid), d.inventory_flaws(()), 5.0, 0.2, ()))
    assert led.survival_rate() == 0.25


def test_empty_ledger_survival_rate_zero():
    assert DistillationLedger().survival_rate() == 0.0


# ── no copied code / no asserted edge ───────────────────────────────────────
def test_distiller_has_no_copy_or_assert_edge():
    d = _d()
    assert not hasattr(d, "copy_code")
    assert not hasattr(d, "import_strategy_code")
    assert not hasattr(d, "assert_edge")


def test_describe_states_no_specialist_is_default():
    from sigbot.strategy_distillation import describe
    out = describe()
    assert "NO_SPECIALIST IS THE DEFAULT" in out
    assert "CAPABILITY_WAS_THE_FLAW" in out
