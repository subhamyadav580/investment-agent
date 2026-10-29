from datetime import UTC, date, datetime

import pytest

from app.schemas.market_data import Consolidation, PeriodType, SourceRef
from app.services.data.providers.screener_provider import (
    build_shareholding,
    build_statements,
    parse_number,
    parse_page,
    parse_period_label,
    quarter_period,
)

NOW = datetime(2026, 10, 24, tzinfo=UTC)
SRC = SourceRef(key="X:financials", provider="screener", source_type="secondary_aggregator", retrieved_at=NOW)


def table(section_id: str, headers: list[str], rows: dict[str, list[str]]) -> str:
    th = "".join(f"<th>{h}</th>" for h in ["", *headers])
    body = "".join(
        f"<tr><td class='text'>{label}&nbsp;<span>+</span></td>{''.join(f'<td>{v}</td>' for v in vals)}</tr>"
        for label, vals in rows.items()
    )
    return f"<section id='{section_id}'><table class='data-table'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></section>"


YEARS = ["Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"]


def company_html(bank: bool = False) -> str:
    if bank:
        pnl = {"Revenue": ["800", "900", "1,000", "1,200"], "Interest": ["400", "450", "500", "600"],
               "Financing Profit": ["100", "120", "150", "180"], "Profit before tax": ["120", "140", "170", "200"],
               "Net Profit": ["90", "105", "128", "150"]}  # fmt: skip
        bs = {"Equity Capital": ["10"] * 4, "Reserves": ["700", "800", "900", "1,000"], "Deposits": ["8,000"] * 4,
              "Borrowing": ["500"] * 4, "Total Assets": ["9,500", "10,000", "11,000", "12,000"]}  # fmt: skip
        quarters = table("quarters", ["Dec 2025", "Mar 2026"], {"Revenue": ["290", "310"], "Net Profit": ["36", "40"],
                                                                "Gross NPA %": ["1.9%", "1.8%"]})  # fmt: skip
    else:
        pnl = {"Sales": ["100", "120", "150", "180"], "Expenses": ["80", "95", "115", "135"],
               "Operating Profit": ["20", "25", "35", "45"], "OPM %": ["20%", "21%", "23%", "25%"],
               "Other Income": ["1", "1", "-0", "2"], "Interest": ["2", "2", "3", "3"],
               "Depreciation": ["4", "5", "6", "7"], "Profit before tax": ["15", "19", "26", "37"],
               "Net Profit": ["11", "14", "19", "28"]}  # fmt: skip
        bs = {"Equity Capital": ["5"] * 4, "Reserves": ["50", "62", "78", "100"], "Borrowings": ["20", "18", "15", "10"],
              "Total Assets": ["120", "135", "150", "170"]}  # fmt: skip
        quarters = table("quarters", ["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
                         {"Sales": ["40", "42", "45", "53", "48", "52"], "Net Profit": ["6", "6.5", "7", "8.5", "8", "9"]})  # fmt: skip
    return f"""<html><body><h1 class='h2'>Example Co Ltd</h1>
    <ul id="top-ratios"><li><span class="name">Market Cap</span><span class="number">2,000</span> Cr.</li>
    <li><span class="name">Current Price</span>₹ <span class="number">400</span></li></ul>
    {quarters}
    {table("profit-loss", [*YEARS, "TTM"], {k: [*v, "999"] for k, v in pnl.items()})}
    {table("balance-sheet", [*YEARS, "Sep 2026"], {k: [*v, "777"] for k, v in bs.items()})}
    {table("cash-flow", YEARS, {"Cash from Operating Activity": ["12", "15", "20", "26"]})}
    {table("ratios", YEARS, {"Debtor Days": ["73", "73", "73", "73"], "ROCE %": ["20%", "21%", "24%", "30%"]})}
    <section id="shareholding"><div id="quarterly-shp">
      {table("shp", ["Jun 2026", "Sep 2026"], {"Promoters": ["60.10%", "59.80%"], "FIIs": ["5%", "6%"]})}
    </div></section>
    <section id="peers"><p class="sub"><a title="Broad Sector">Industrials</a><a title="Sector">Capital Goods</a>
      <a title="Broad Industry">Electrical Equipment</a><a title="Industry">Heavy Electrical Equipment</a></p></section>
    </body></html>"""


def test_number_and_period_parsing():
    assert parse_number("1,62,579") == 162579 and parse_number("36%") == 36 and parse_number("-0") == 0
    assert parse_number("") is None and parse_number("abc") is None
    assert parse_period_label("Mar 2026") == date(2026, 3, 31) and parse_period_label("TTM") is None
    assert [quarter_period(date(2026, m, 28)) for m in (6, 9, 12, 3)] == ["Q1FY2027", "Q2FY2027", "Q3FY2027", "Q4FY2026"]


def test_non_financial_company_mapping():
    page = parse_page(company_html())
    assert page.name == "Example Co Ltd"
    assert page.classification["Sector"] == "Capital Goods"
    fin, lender = build_statements(page, "X", SRC, Consolidation.CONSOLIDATED)
    assert not lender
    assert fin.periods() == ["FY2023", "FY2024", "FY2025", "FY2026"]  # TTM / half-year columns ignored
    s = lambda m: fin.series(m)["FY2026"]  # noqa: E731
    assert s("revenue") == 180 and s("operating_profit") == 45 and s("pbt") == 37 and s("net_profit") == 28
    assert s("total_equity") == 105 and s("total_debt") == 10 and s("cfo") == 26 and s("total_assets") == 170
    assert s("receivables") == pytest.approx(73 * 180 / 365)
    assert 777 not in fin.series("total_debt").values()
    assert fin.shares_outstanding_cr == pytest.approx(5.0)
    assert fin.series("net_profit", PeriodType.QUARTER)["Q2FY2027"] == 9
    assert all(v.source_key == "X:financials" for v in fin.values)


def test_lender_mapping():
    fin, lender = build_statements(parse_page(company_html(bank=True)), "B", SRC, Consolidation.STANDALONE)
    assert lender
    s = lambda m: fin.series(m)["FY2026"]  # noqa: E731
    assert s("net_interest_income") == 600 and s("total_debt") == 500 and s("total_equity") == 1010
    assert s("gross_npa_pct") == 1.8  # March-quarter value carried into the fiscal year
    assert {v.consolidation for v in fin.values} == {Consolidation.STANDALONE}


def test_shareholding():
    out = build_shareholding(parse_page(company_html()), "X", "https://x", NOW)
    assert [(s.period_end, s.promoter_holding_pct) for s in out] == [(date(2026, 6, 30), 60.1), (date(2026, 9, 30), 59.8)]


def test_page_without_financials():
    page = parse_page("<html><h1>Empty</h1></html>")
    assert not page.has_annual_data()
    fin, _ = build_statements(page, "E", SRC, Consolidation.CONSOLIDATED)
    assert fin.values == []


def test_quarterly_growth_metrics_and_screening_inputs():
    from app.schemas.market_data import CompanyData
    from app.services.research.metrics import compute_metrics

    fin, _ = build_statements(parse_page(company_html()), "X", SRC, Consolidation.CONSOLIDATED)
    m = compute_metrics(CompanyData(symbol="X", financials=fin), "non_financial", date(2026, 10, 24))
    assert m["profit_growth_q_yoy"].value == pytest.approx(9 / 6.5 - 1, abs=1e-5)  # Sep 2026 vs Sep 2025
    assert m["revenue_growth_q_yoy"].value == pytest.approx(52 / 42 - 1, abs=1e-5)
    assert m["profit_growth_q_yoy_prev"].value == pytest.approx(8 / 6 - 1, abs=1e-5)
    assert m["roce_latest"].value is not None and m["cfo_to_pat_3y"].value is not None
