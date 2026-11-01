from datetime import date

import pytest

from app.services.discovery.company_evaluator import evaluate, prepare
from app.services.discovery.scoring import scale
from app.services.discovery.screening_rules import detect_governance_flags
from app.services.discovery.sector_classifier import FINANCIAL, classify_sector_group
from tests.fixtures.builders import announcement, company_data, healthy_annual, shareholding

AS_OF = date(2026, 10, 24)


def run(cfg, data, group="non_financial", medians=None):
    return evaluate(prepare(data, "Industrials", group, AS_OF, cfg), medians, AS_OF, cfg)


def rule(ev, rule_id):
    return next(r for r in ev.rules if r.rule_id == rule_id)


def test_healthy_company_is_candidate(cfg):
    ev = run(cfg, company_data())
    assert ev.evaluation.status == "candidate"
    assert 0 < ev.evaluation.score <= 100
    assert set(ev.evaluation.dimension_scores) == set(cfg.scoring.weights)


def test_missing_metric_never_passes(cfg):
    annual = healthy_annual()
    for y in (2024, 2025):
        annual[y]["cfo"] = None
    ev = run(cfg, company_data(annual))
    assert rule(ev, "cash_conversion").status == "missing"
    assert "financial_performance.cfo_to_pat_3y" in ev.evaluation.missing_components


def test_hard_fail_rejects(cfg):
    annual = healthy_annual()
    for y in annual:
        annual[y]["interest"] = annual[y]["pbt"]  # coverage ~ 2x pbt/interest -> force below 1.5
        annual[y]["pbt"] = annual[y]["interest"] * 0.2
    ev = run(cfg, company_data(annual))
    assert ev.evaluation.status == "rejected"
    assert any("interest_coverage_critical" in r for r in ev.evaluation.exclusion_reasons)


def test_serious_governance_is_not_averaged_away(cfg):
    data = company_data(announcements=[announcement("auditor_resignation", date(2026, 9, 1))])
    ev = run(cfg, data)
    assert ev.evaluation.status == "governance_review"
    assert ev.evaluation.dimension_scores["management_governance"] == 0.0


def test_old_governance_event_outside_lookback_ignored(cfg):
    data = company_data(announcements=[announcement("sebi_order", date(2024, 1, 1))])
    assert run(cfg, data).evaluation.status == "candidate"


def test_pledge_thresholds(cfg):
    g = cfg.governance
    warn = detect_governance_flags(company_data(shareholding=[shareholding(date(2026, 9, 30), 50, 25)]), AS_OF, g)
    assert [f.code for f in warn] == ["promoter_pledge_elevated"]
    serious = detect_governance_flags(company_data(shareholding=[shareholding(date(2026, 9, 30), 50, 60)]), AS_OF, g)
    assert serious[0].severity == "serious"
    drop = detect_governance_flags(
        company_data(shareholding=[shareholding(date(2025, 9, 30), 60, 0), shareholding(date(2026, 9, 30), 50, 0)]),
        AS_OF, g,
    )  # fmt: skip
    assert [f.code for f in drop] == ["promoter_holding_drop"]


def test_five_categories_use_sector_weights(cfg):
    assert set(cfg.scoring.weights) == {"business_quality", "financial_performance", "financial_strength", "valuation",
                                        "management_governance"}  # fmt: skip
    assert cfg.scoring.weights_for("non_financial")["business_quality"] == 0.25
    assert cfg.scoring.weights_for(FINANCIAL)["financial_strength"] == 0.25


def test_bank_rules_are_sector_aware(cfg):
    annual = {y: {"revenue": 900.0 * 1.15 ** (y - 2021), "net_profit": 150.0 * 1.15 ** (y - 2021),
                  "total_equity": 1000.0 * 1.15 ** (y - 2021), "total_assets": 10000.0 * 1.15 ** (y - 2021),
                  "gross_npa_pct": 2.0, "capital_adequacy_ratio": 18.0} for y in range(2021, 2027)}  # fmt: skip
    ev = run(cfg, company_data(annual), group=FINANCIAL)
    assert rule(ev, "leverage").status == "not_applicable"
    assert rule(ev, "cash_conversion").status == "not_applicable"
    assert rule(ev, "return_on_equity").status == "pass"
    assert rule(ev, "asset_quality").status == "pass"


def test_ineligible_data_short_circuits(cfg):
    ev = run(cfg, company_data(healthy_annual(range(2025, 2027))))
    assert ev.evaluation.status == "ineligible"
    assert [r.rule_id for r in ev.rules] == ["data_eligible"]
    assert ev.evaluation.score is None


def test_sector_relative_valuation(cfg):
    base = run(cfg, company_data())
    pe = base.values["pe"]
    cheap = run(cfg, company_data(), medians={"pe": pe * 2})
    rich = run(cfg, company_data(), medians={"pe": pe / 2})
    assert rule(cheap, "pe_vs_sector").status == "pass"
    assert rule(rich, "pe_vs_sector").status == "fail"
    assert cheap.evaluation.dimension_scores["valuation"] > rich.evaluation.dimension_scores["valuation"]
    # no peers: not applicable, and not scored as missing company data
    assert rule(base, "pe_vs_sector").status == "not_applicable"
    assert "valuation.pe_vs_sector (no sector peers)" in base.evaluation.missing_components


def test_scale_is_clamped_and_supports_inverse():
    assert scale(0.30, 0.05, 0.30) == 100
    assert scale(0.50, 0.05, 0.30) == 100
    assert scale(1.0, 2.0, 0.0) == pytest.approx(50)
    assert scale(3.0, 2.0, 0.0) == 0


def test_sector_classifier():
    assert classify_sector_group("Financial Services", "Small Finance Bank") == (FINANCIAL, False)
    assert classify_sector_group("Industrials", "Machinery") == ("non_financial", False)
    assert classify_sector_group(None, None, "Some Housing Finance Ltd") == (FINANCIAL, True)
