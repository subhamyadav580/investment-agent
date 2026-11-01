from datetime import date

from app.services.discovery.company_evaluator import evaluate, prepare
from app.services.research.assessment import AssessmentInputs, build_assessment
from app.services.research.metrics import historical_pe
from app.services.research.valuation import evaluate_valuation
from tests.fixtures.builders import announcement, company_data, healthy_annual, prices, shareholding

AS_OF = date(2026, 10, 24)
HOLDINGS = [shareholding(date(2025, 9, 30), 60, 0), shareholding(date(2026, 9, 30), 60, 0)]


def assess(cfg, data, medians=None, unverified=0, primary="long_term"):
    ev = evaluate(prepare(data, "Industrials", "non_financial", AS_OF, cfg), medians, AS_OF, cfg)
    valuation = evaluate_valuation(ev.prepared.metrics, historical_pe(data.financials, data.prices), medians,
                                   "non_financial", data.financials.shares_outstanding_cr, cfg.valuation,
                                   horizons={"long_term": 5, "medium_term": 2})  # fmt: skip
    inputs = AssessmentInputs(
        sector_group="non_financial", metrics=ev.prepared.metrics, values=ev.values,
        dimension_scores=ev.evaluation.dimension_scores, missing_components=ev.evaluation.missing_components,
        score=ev.evaluation.score, flags=ev.flags, rules=ev.rules, data_quality=ev.prepared.data_quality,
        valuation=valuation, unverified_material=unverified, financial_source_keys=["T:fin"],
        price_source_keys=["T:prices"], shareholding_source_keys=[h.source.key for h in data.shareholding],
        horizon_scores=ev.evaluation.horizon_scores, medium_term_scores=ev.evaluation.medium_term_scores,
        medium_term_missing=ev.evaluation.medium_term_missing, earnings_basis=ev.evaluation.earnings_basis,
        catalysts=ev.evaluation.catalysts, primary_horizon=primary,
    )  # fmt: skip
    return build_assessment(inputs, cfg, {"T:fin": "E1", "T:prices": "E2"})


def high_return_annual():
    annual = healthy_annual()
    for y in annual:
        annual[y]["total_equity"] = annual[y]["revenue"] * 0.45  # capital-light: ROCE ~35%
    return annual


def test_strong_business_at_a_reasonable_price(cfg):
    a = assess(cfg, company_data(high_return_annual(), shareholding=HOLDINGS), medians={"pe": 20.0})
    assert a["business_quality"]["rating"] == "Strong" and a["financial_health"]["rating"] == "Strong"
    assert a["valuation"]["rating"] in ("Attractive", "Fair")
    assert a["overall"]["classification"] == "strong_candidate", a["overall"]["reasons"]
    assert a["business_quality"]["evidence_ids"] == ["E1"] and "roce_avg_3y" in a["business_quality"]["metric_refs"]


def test_great_business_too_expensive(cfg):
    data = company_data(high_return_annual(), price=prices(date(2026, 10, 23), 3000.0), shareholding=HOLDINGS)
    a = assess(cfg, data, medians={"pe": 20.0})
    assert a["business_quality"]["rating"] == "Strong" and a["valuation"]["rating"] == "Expensive"
    assert a["overall"]["classification"] == "good_business_expensive"


def test_red_flag_is_not_hidden_by_a_high_score(cfg):
    data = company_data(high_return_annual(), shareholding=HOLDINGS,
                        announcements=[announcement("auditor_resignation", date(2026, 9, 1), "Auditor resigns")])  # fmt: skip
    a = assess(cfg, data, medians={"pe": 20.0})
    assert a["business_quality"]["rating"] == "Strong"
    assert a["overall"]["classification"] == "high_risk"
    assert [f["code"] for f in a["red_flags"]] == ["auditor_resignation"]
    assert a["management_governance"]["rating"] == "Concerning"


def test_cash_flow_divergence_is_a_red_flag(cfg):
    annual = high_return_annual()
    for y in annual:
        annual[y]["cfo"] = annual[y]["net_profit"] * 0.1
    a = assess(cfg, company_data(annual, shareholding=HOLDINGS), medians={"pe": 20.0})
    assert "cash_flow_divergence" in [f["code"] for f in a["red_flags"]]
    assert a["overall"]["classification"] == "high_risk"


def test_unverified_claims_and_weak_data_downgrade(cfg):
    a = assess(cfg, company_data(high_return_annual(), shareholding=HOLDINGS), medians={"pe": 20.0}, unverified=2)
    assert a["overall"]["classification"] == "potential_opportunity"
    assert a["data_quality"]["rating"] == "Medium"
    ineligible = assess(cfg, company_data(healthy_annual(range(2025, 2027))))
    assert ineligible["overall"]["classification"] == "insufficient_evidence"
