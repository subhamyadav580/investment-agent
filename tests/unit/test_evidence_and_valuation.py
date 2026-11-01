import pytest

from app.schemas.research import Claim
from app.schemas.screening import Metric
from app.services.research.evidence import build_evidence, verify_claims
from app.services.research.peer_comparison import compare_to_peers, sector_medians
from app.services.research.valuation import assess_valuation, evaluate_valuation
from tests.fixtures.builders import src

METRICS = {
    "roce_latest": Metric(key="roce_latest", value=0.2134, unit="ratio"),
    "pe": Metric(key="pe", value=28.4, unit="x", period="FY2026", inputs={"earnings": 100.0}),
    "gross_npa_pct": Metric(key="gross_npa_pct", value=2.5, unit="pct"),
    "pb": Metric(key="pb", value=None, unit="x"),
}
KNOWN = {"E1", "E2"}


def claim(statement, ev=(), m=(), materiality="material"):
    return Claim(statement=statement, evidence_ids=list(ev), metric_refs=list(m), materiality=materiality)


def test_supported_claim_verifies():
    [v] = verify_claims("b", [claim("ROCE was 21.3% in FY2026.", ["E1"], ["roce_latest"])], KNOWN, METRICS)
    assert v.verified, v.problems


def test_invented_number_is_flagged():
    [v] = verify_claims("b", [claim("ROCE was 35% in FY2026.", ["E1"], ["roce_latest"])], KNOWN, METRICS)
    assert not v.verified and "35% does not match" in v.problems[0]


def test_unknown_ids_and_null_metrics_flagged():
    [v] = verify_claims("b", [claim("Cheap on book.", ["E9"], ["pb", "made_up"])], KNOWN, METRICS)
    assert not v.verified
    assert any("unknown evidence" in p for p in v.problems)
    assert any("unknown metrics" in p for p in v.problems)
    assert any("no value" in p for p in v.problems)


def test_material_claim_needs_support_minor_does_not():
    material, minor = verify_claims(
        "b", [claim("Management is excellent."), claim("Industry is competitive.", materiality="minor")], KNOWN, METRICS
    )
    assert not material.verified and minor.verified


def test_multiples_and_pct_units():
    [v] = verify_claims("v", [claim("Trades at 28.4x earnings with GNPA of 2.5%.", m=["pe"])], KNOWN, METRICS)
    assert v.verified, v.problems


def test_evidence_ids_are_stable_and_ordered():
    sources = {s.key: s for s in [src("b:prices", "price_feed"), src("a:fin", "annual_report")]}
    items, key_by_id = build_evidence(sources)
    assert [i.id for i in items] == ["E1", "E2"] and key_by_id == {"E1": "a:fin", "E2": "b:prices"}


def test_sector_medians_require_min_peers():
    vals = {"A": {"pe": 10}, "B": {"pe": 20}, "C": {"pe": 30}, "D": {"pe": 5}}
    meds = sector_medians(vals, {"A": "X", "B": "X", "C": "X", "D": "Y"})
    assert meds["X"]["pe"] == 20 and "pe" not in meds["Y"]
    table = compare_to_peers("A", vals["A"], {k: v for k, v in vals.items() if k != "D"})
    assert table["metrics"]["pe"]["peer_median"] == 25 and table["metrics"]["pe"]["percentile"] == 0


GROWTH = {
    "last_price": Metric(key="last_price", value=284.0, unit="INR"),
    "profit_cagr": Metric(key="profit_cagr", value=0.30, unit="ratio", period="FY2021-FY2026"),
    "revenue_cagr": Metric(key="revenue_cagr", value=0.12, unit="ratio", period="FY2021-FY2026"),
}


def test_scenarios_state_assumptions(cfg):
    hist = {"FY2023": 20.0, "FY2024": 25.0, "FY2025": 30.0, "FY2026": 22.0}
    v = evaluate_valuation({**METRICS, **GROWTH}, hist, {"pe": 25.0}, "non_financial", 10.0, cfg.valuation)
    assert v["vs_sector"]["pe"] == pytest.approx(28.4 / 25)
    assert v["history"]["position"] == "above_history"
    sc = v["scenarios"]
    assert sc["per_share"] == 10.0 and sc["years"] == cfg.valuation.scenario_years
    # profit CAGR 30% is capped at revenue CAGR 12% + 5 pp headroom; conservative/optimistic = base -/+ 5 pp
    assert [sc[k]["annual_growth"] for k in ("conservative", "base", "optimistic")] == pytest.approx([0.12, 0.17, 0.22])
    assert sc["conservative"]["exit_multiple"] < sc["base"]["exit_multiple"] < sc["optimistic"]["exit_multiple"]
    assert any("cap applied" in a for a in v["assumptions"]) and len(v["assumptions"]) >= 5
    assert any("not forecasts" in x for x in v["limitations"])
    rating, reasons = assess_valuation(v, METRICS, cfg.valuation)
    assert rating in ("Attractive", "Fair", "Expensive") and any("Implied annual" in r for r in reasons)


def test_scenarios_fall_back_to_sector_multiple(cfg):
    v = evaluate_valuation({**METRICS, **GROWTH}, {"FY2026": 22.0}, {"pe": 25.0}, "non_financial", 10.0, cfg.valuation)
    assert v["scenarios"]["base"]["exit_multiple"] == 25.0 and v["scenarios"]["conservative"]["exit_multiple"] == 20.0
    assert any("sector median" in a for a in v["assumptions"])


def test_no_history_no_peers_is_uncertain(cfg):
    v = evaluate_valuation({**METRICS, **GROWTH}, {"FY2026": 22.0}, None, "non_financial", 10.0, cfg.valuation)
    assert v["scenarios"] is None
    assert assess_valuation(v, METRICS, cfg.valuation)[0] == "Uncertain"


def test_expensive_when_price_outruns_growth(cfg):
    pricey = {**METRICS, **GROWTH, "pe": Metric(key="pe", value=95.0, unit="x", inputs={"earnings": 100.0})}
    v = evaluate_valuation(pricey, {}, {"pe": 25.0}, "non_financial", 10.0, cfg.valuation)
    rating, reasons = assess_valuation(v, pricey, cfg.valuation)
    assert rating == "Expensive" and any("ceiling" in r for r in reasons)


def test_reference_numbers_such_as_thresholds_are_allowed():
    c = claim("ROCE comfortably clears the 15% hurdle; sector median P/E is 25x.", m=["roce_latest"])
    [flagged] = verify_claims("b", [c], KNOWN, METRICS)
    assert not flagged.verified
    [ok] = verify_claims("b", [c], KNOWN, METRICS, reference_numbers=[0.15, 25.0])
    assert ok.verified, ok.problems
