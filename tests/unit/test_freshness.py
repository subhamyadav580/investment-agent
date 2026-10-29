from datetime import date

from app.schemas.market_data import Consolidation, FinancialValue
from app.services.data.freshness import validate_company_data
from app.services.discovery.rules_config import EligibilityCfg
from app.services.discovery.sector_classifier import FINANCIAL
from tests.fixtures.builders import company_data, healthy_annual, prices, src

AS_OF = date(2026, 10, 24)
CFG = EligibilityCfg()


def codes(report):
    return {i.code for i in report.issues}


def test_clean_data_is_eligible():
    r = validate_company_data(company_data(), "non_financial", AS_OF, CFG)
    assert r.is_eligible and r.years_available == 6 and r.latest_period == "FY2026"
    assert r.score == 100.0


def test_no_financials_is_ineligible():
    r = validate_company_data(company_data(annual={}), "non_financial", AS_OF, CFG)
    assert not r.is_eligible and "no_financials" in codes(r)


def test_stale_financials():
    r = validate_company_data(company_data(healthy_annual(range(2019, 2024))), "non_financial", AS_OF, CFG)
    assert not r.is_eligible and "stale_financials" in codes(r)


def test_short_history_error_and_warning():
    assert "insufficient_history" in codes(
        validate_company_data(company_data(healthy_annual(range(2025, 2027))), "non_financial", AS_OF, CFG)
    )
    r = validate_company_data(company_data(healthy_annual(range(2023, 2027))), "non_financial", AS_OF, CFG)
    assert r.is_eligible and "short_history" in codes(r)


def test_missing_required_field_latest_is_error():
    annual = healthy_annual()
    annual[2026]["cfo"] = None
    r = validate_company_data(company_data(annual), "non_financial", AS_OF, CFG)
    assert not r.is_eligible
    assert any(i.code == "missing_required_field" and i.field == "cfo" for i in r.issues)


def test_financials_have_different_required_fields():
    annual = {y: {"revenue": 100.0, "net_profit": 10.0, "total_equity": 90.0, "total_assets": 900.0}
              for y in range(2021, 2027)}  # fmt: skip
    r = validate_company_data(company_data(annual), FINANCIAL, AS_OF, CFG)
    assert r.is_eligible  # no cfo/total_debt required for a lender


def test_conflicting_sources_and_mixed_consolidation_are_flagged():
    data = company_data()
    alt = src("T:alt", "secondary")
    data.financials.sources[alt.key] = alt
    data.financials.values.append(FinancialValue(period="FY2025", period_end=date(2025, 3, 31), metric="revenue",
                                                 value=1.0, consolidation=Consolidation.STANDALONE,
                                                 source_key=alt.key))  # fmt: skip
    r = validate_company_data(data, "non_financial", AS_OF, CFG)
    assert {"conflicting_values", "mixed_consolidation"} <= codes(r)
    assert r.is_eligible  # flagged, not silently resolved


def test_stale_prices_and_missing_period():
    annual = healthy_annual()
    del annual[2023]
    r = validate_company_data(company_data(annual, price=prices(date(2026, 9, 1), 100.0)), "non_financial", AS_OF, CFG)
    assert {"stale_prices", "missing_period"} <= codes(r)


def test_future_dated_data_is_not_used_by_enrichment(providers):
    from app.services.discovery.data_enrichment import fetch_company_data

    data = fetch_company_data(providers, "SMPLALPHA", date(2025, 1, 1))
    assert max(v.period_end for v in data.financials.values) <= date(2025, 1, 1)
    assert data.prices.bars[-1].date <= date(2025, 1, 1)


def test_cash_flow_outlier_and_balance_jump_are_flagged():
    annual = healthy_annual()
    annual[2026]["cfo"] = annual[2026]["operating_profit"] * 6
    annual[2026]["total_assets"] = 10_000.0
    annual[2025]["total_assets"] = 1_000.0
    r = validate_company_data(company_data(annual), "non_financial", AS_OF, CFG)
    assert {"cash_flow_outlier", "balance_jump"} <= codes(r) and r.is_eligible
