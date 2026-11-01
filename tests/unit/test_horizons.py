from datetime import date

import pytest

from app.services.discovery.scoring import catalyst_signals, medium_term_scores
from app.services.research.request_router import HorizonError, parse_request
from tests.fixtures.builders import announcement, company_data
from tests.unit.test_assessment import HOLDINGS, assess, high_return_annual

AS_OF = date(2026, 10, 24)


@pytest.mark.parametrize(("text", "query", "horizon", "years"), [
    ("Research Asian Paints for a 5-year investment", "Asian Paints", "long_term", {"long_term": 5, "medium_term": 2}),
    ("ESDS for the next 2 years", "ESDS", "medium_term", {"long_term": 5, "medium_term": 2}),
    ("research TCS for 3 years", "TCS", "medium_term", {"long_term": 5, "medium_term": 3}),
    ("Asian Paints over 7 yrs", "Asian Paints", "long_term", {"long_term": 7, "medium_term": 2}),
    ("Infosys medium-term", "Infosys", "medium_term", {"long_term": 5, "medium_term": 2}),
    ("Infosys for both long and medium term", "Infosys", "both", {"long_term": 5, "medium_term": 2}),
    ("SMPLALPHA", "SMPLALPHA", "long_term", {"long_term": 5, "medium_term": 2}),
])  # fmt: skip
def test_request_router(cfg, text, query, horizon, years):
    spec = parse_request(text, cfg.horizons)
    assert (spec.query, spec.horizon, spec.years) == (query, horizon, years)


def test_router_rejects_gaps_and_explicit_options_win(cfg):
    with pytest.raises(HorizonError, match="neither horizon"):
        parse_request("ESDS for 4 years", cfg.horizons)
    with pytest.raises(HorizonError, match="outside"):
        parse_request("ESDS", cfg.horizons, horizon="medium_term", years=6)
    spec = parse_request("ESDS for 5 years", cfg.horizons, horizon="medium_term", years=1)
    assert spec.horizon == "medium_term" and spec.years["medium_term"] == 1


def test_catalysts_come_only_from_evidence(cfg):
    m = cfg.horizons.medium_term
    anns = [announcement("order_win", date(2026, 9, 1), "Order worth Rs 500 cr"),
            announcement("order_win", date(2026, 8, 1)), announcement("board_meeting", date(2026, 9, 2)),
            announcement("capacity_expansion", date(2025, 1, 1))]  # fmt: skip  (too old)
    score, items = catalyst_signals(anns, AS_OF, False, m)
    assert score == m.catalyst_points and [i["kind"] for i in items] == ["order_win"]
    assert items[0]["title"] == "Order worth Rs 500 cr"
    score, items = catalyst_signals([], AS_OF, True, m)
    assert score == m.industry_tailwind_points and items[0]["kind"] == "industry_tailwind"
    assert catalyst_signals([], AS_OF, False, m) == (0.0, [])


def test_medium_term_uses_quarterly_momentum_else_annual():
    dims = {"business_quality": 80, "financial_performance": 60, "financial_strength": 70, "valuation": 50,
            "management_governance": 90}  # fmt: skip
    annual = {"revenue_growth_latest": 0.15, "profit_growth_latest": 0.25, "profit_cagr": 0.10}
    scores, missing, basis = medium_term_scores(annual, dims, 40.0)
    assert basis == "annual" and missing == [] and scores["business_financial_quality"] == 70
    assert scores["catalysts"] == 40 and scores["management_risk"] == 90
    fading = medium_term_scores({**annual, "profit_growth_q_yoy": 0.0, "profit_growth_q_yoy_prev": 0.3,
                                 "revenue_growth_q_yoy": 0.02}, dims, 0.0)  # fmt: skip
    assert fading[2] == "quarterly" and fading[0]["earnings_outlook"] < scores["earnings_outlook"]


def test_same_company_can_differ_by_horizon(cfg):
    a = assess(cfg, company_data(high_return_annual(), shareholding=HOLDINGS), medians={"pe": 20.0})
    lt, mt = a["horizons"]["long_term"], a["horizons"]["medium_term"]
    assert lt["years"] == 5 and mt["years"] == 2
    assert lt["valuation"]["rating"] and mt["earnings_outlook"]["rating"] and mt["catalysts"]["rating"] == "None visible"
    assert a["overall"]["horizon"] == "long_term" and a["overall"]["classification"] == lt["classification"]
    assert lt["main_concern"] and mt["main_concern"]
