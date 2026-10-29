from datetime import date

import pytest

from app.services.discovery.sector_classifier import FINANCIAL
from app.services.research.metrics import ICR_CAP, cagr, compute_metrics, historical_pe, ttm_net_profit
from tests.fixtures.builders import company_data, healthy_annual, prices, statements

AS_OF = date(2026, 10, 24)


def test_cagr_basic_and_undefined_cases():
    assert cagr(100, 200, 5) == pytest.approx(2 ** (1 / 5) - 1)
    assert cagr(-10, 50, 3) is None  # negative start: CAGR is meaningless, never invented
    assert cagr(100, 0, 3) is None
    assert cagr(100, 200, 0) is None
    assert cagr(None, 200, 3) is None


def test_growth_metrics_use_five_year_window():
    m = compute_metrics(company_data(), "non_financial", AS_OF)
    assert m["revenue_cagr"].value == pytest.approx(0.12, abs=1e-6)
    assert m["revenue_cagr"].period == "FY2021-FY2026"
    assert m["revenue_cagr"].inputs["years"] == 5
    assert m["profit_positive_ratio"].value == 1.0


def test_roce_roe_leverage_hand_calculated():
    annual = {
        2025: {"revenue": 1000, "operating_profit": 200, "pbt": 150, "interest": 10, "net_profit": 110,
               "total_equity": 900, "total_debt": 100, "cfo": 100},
        2026: {"revenue": 1200, "operating_profit": 240, "pbt": 190, "interest": 10, "net_profit": 140,
               "total_equity": 1000, "total_debt": 200, "cfo": 150, "cash_and_equivalents": 50},
    }  # fmt: skip
    m = compute_metrics(company_data(annual), "non_financial", AS_OF)
    # EBIT = 190 + 10 = 200; avg capital employed = ((900+100) + (1000+200)) / 2 = 1100
    assert m["roce_latest"].value == pytest.approx(200 / 1100, rel=1e-5)
    # ROE = 140 / avg equity 950
    assert m["roe_latest"].value == pytest.approx(140 / 950, rel=1e-5)
    assert m["debt_to_equity"].value == pytest.approx(0.2)
    assert m["interest_coverage"].value == pytest.approx(20.0)
    assert m["net_debt_cr"].value == pytest.approx(150.0)
    assert m["operating_margin_latest"].value == pytest.approx(0.2)
    assert m["revenue_growth_latest"].value == pytest.approx(0.2)


def test_zero_interest_caps_coverage_with_note():
    annual = healthy_annual()
    for y in annual:
        annual[y]["interest"] = 0.0
    m = compute_metrics(company_data(annual), "non_financial", AS_OF)
    assert m["interest_coverage"].value == ICR_CAP
    assert "no interest" in m["interest_coverage"].note


def test_cash_conversion_and_missing_inputs():
    annual = healthy_annual()
    m = compute_metrics(company_data(annual), "non_financial", AS_OF)
    assert m["cfo_to_pat_3y"].value == pytest.approx(0.95)
    annual[2025]["cfo"] = None
    m = compute_metrics(company_data(annual), "non_financial", AS_OF)
    assert m["cfo_to_pat_3y"].value is None
    assert m["cfo_to_pat_3y"].note


def test_valuation_metrics_from_price_and_shares():
    annual = healthy_annual()
    data = company_data(annual, price=prices(date(2026, 10, 23), 250.0))
    m = compute_metrics(data, "non_financial", AS_OF)
    mcap = 250.0 * 10.0  # price x shares (crore)
    assert m["market_cap_cr"].value == pytest.approx(mcap)
    assert m["pe"].value == pytest.approx(mcap / annual[2026]["net_profit"])
    assert m["pe"].period == "FY2026"
    assert m["avg_traded_value_cr_60d"].value == pytest.approx(250.0 * 1_000_000 / 1e7)


def test_loss_making_company_has_no_pe():
    annual = healthy_annual()
    annual[2026]["net_profit"] = -5.0
    m = compute_metrics(company_data(annual), "non_financial", AS_OF)
    assert m["pe"].value is None
    assert m["profit_positive_ratio"].value == pytest.approx(4 / 5)


def test_financial_sector_skips_industrial_ratios():
    annual = {y: {"revenue": 100.0 + y, "net_profit": 15.0, "total_equity": 120.0, "total_assets": 1000.0,
                  "gross_npa_pct": 2.1, "capital_adequacy_ratio": 17.0} for y in range(2022, 2027)}  # fmt: skip
    m = compute_metrics(company_data(annual), FINANCIAL, AS_OF)
    assert "debt_to_equity" not in m and "cfo_to_pat_3y" not in m and "roce_latest" not in m
    assert m["roa_latest"].value == pytest.approx(0.015)
    assert m["gross_npa_pct"].value == 2.1


def test_ttm_prefers_newer_quarters():
    from app.schemas.market_data import FinancialValue, PeriodType

    fin = statements(healthy_annual())
    for i, (q, end) in enumerate([("Q1FY2027", date(2026, 6, 30)), ("Q4FY2026", date(2026, 3, 31)),
                                  ("Q3FY2026", date(2025, 12, 31)), ("Q2FY2026", date(2025, 9, 30))]):  # fmt: skip
        fin.values.append(FinancialValue(period=q, period_end=end, period_type=PeriodType.QUARTER,
                                         metric="net_profit", value=50.0 + i, source_key="T:fin"))  # fmt: skip
    value, basis = ttm_net_profit(fin)
    assert value == pytest.approx(50 + 51 + 52 + 53)
    assert basis.startswith("TTM to 2026-06-30")


def test_historical_pe_avoids_lookahead():
    fin = statements(healthy_annual())
    hist = historical_pe(fin, prices(date(2026, 10, 23), 100.0, days=2000))
    # price used for FY2026 is the close ~60 days after 2026-03-31, i.e. known by then
    assert set(hist) == {f"FY{y}" for y in range(2021, 2027)}
    assert hist["FY2026"] == pytest.approx(100.0 * 10.0 / healthy_annual()[2026]["net_profit"])
