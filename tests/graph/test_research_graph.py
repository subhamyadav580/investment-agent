import pytest

from app.models import Alert, ResearchReport, Watchlist, WatchlistCompany
from app.repos.company_repo import CompanyRepo
from app.schemas.research import BusinessAnalysis, Claim, RiskAnalysis, RiskItem, ValuationCommentary
from app.services.discovery.screening_service import run_screening
from app.services.graph.deps import GraphDeps
from app.services.research.research_service import ResearchError, ResearchService
from tests.conftest import AS_OF, FakeLLM


def outputs(bad_claim: bool = False):
    claims = [Claim(statement="Return on capital is well above the 15% hurdle.", evidence_ids=["E1"],
                    metric_refs=["roce_latest"], materiality="material")]  # fmt: skip
    if bad_claim:
        claims.append(Claim(statement="Revenue grew 45% last year.", evidence_ids=["E99"], metric_refs=[],
                            materiality="material"))  # fmt: skip
    return {
        BusinessAnalysis: BusinessAnalysis(
            business_overview="Makes machines.", revenue_model="Sells capital equipment to factories.",
            competitive_advantages=["High returns on capital"], competitive_position="Strong returns.",
            financial_trends="Steady growth.", industry_outlook="Not visible in the evidence.", growth_drivers=[],
            competitive_threats=[], claims=claims, open_questions=["Order book?"],
        ),
        ValuationCommentary: ValuationCommentary(summary="In line with history.", scenario_commentary="Base case.", medium_term_view="Momentum steady.",
                                                 claims=[]),  # fmt: skip
        RiskAnalysis: RiskAnalysis(
            management_assessment="No pledging.",
            risks=[RiskItem(category="business", description="Cyclical capex demand.", severity="medium",
                            evidence_ids=["E1"], metric_refs=["revenue_cagr"])],  # fmt: skip
            downside_scenarios=["Capex slowdown"], catalysts=[], monitor_next=["Q2 margins"],
            invalidation_conditions=["ROCE below 15% for two years"],
        ),
    }


def service(session, providers, cfg, llm):
    deps = GraphDeps(session=session, providers=providers, cfg=cfg, llm=llm, prompt_version="v1", quiet_hours=72,
                     report_base_url="http://test")  # fmt: skip
    return ResearchService(deps)


@pytest.fixture
def screened(session, providers, cfg):
    run_screening(session, providers, cfg, AS_OF, enqueue_top_n=0)


def test_full_graph_with_verified_claims(session, providers, cfg, screened):
    llm = FakeLLM(outputs())
    outcome = service(session, providers, cfg, llm).research("SMPLALPHA", AS_OF)
    assert [c["task"] for c in llm.calls] == ["business_analysis", "valuation_commentary", "risk_analysis"]
    report = session.get(ResearchReport, outcome.report_id)
    doc = report.report_json
    assert doc["research_status"] == "complete"
    assert doc["conclusion"] == "strong_candidate" and doc["conclusion_label"] == "Strong candidate"
    assert all(c["verified"] for c in doc["claims"])
    assert doc["company_overview"]["what_it_does"] == "Makes machines."
    assert doc["company_overview"]["revenue_model"] and doc["management_governance"]["commentary"] == "No pledging."
    fa = doc["final_assessment"]
    assert {k: fa[k]["rating"] for k in ("business_quality", "financial_health", "management_governance",
                                         "data_quality")} == {"business_quality": "Strong", "financial_health": "Strong",
                                                              "management_governance": "Positive", "data_quality": "High"}  # fmt: skip
    assert fa["valuation"]["rating"] in ("Attractive", "Fair") and fa["overall"]["classification"] == doc["conclusion"]
    assert all(fa[k]["reasons"] and fa[k]["evidence_ids"] for k in ("business_quality", "financial_health", "valuation"))
    assert doc["risks"]["red_flags"] == [] and doc["risks"]["invalidation_conditions"]
    assert set(doc["valuation"]["scenarios"]) >= {"conservative", "base", "optimistic"}
    assert doc["valuation"]["scenario_commentary"] == "Base case."
    assert doc["peer_comparison"]["peers"]  # peers came from the screening run
    assert doc["valuation"]["history"]  # deterministic valuation computed in-graph
    assert report.rules_version == cfg.version and report.prompt_version == "v1"
    assert report.model_version == "fake-llm" and report.source_snapshot
    assert report.llm_usage["calls"] == 3


def test_unverifiable_claim_downgrades_report(session, providers, cfg, screened):
    outcome = service(session, providers, cfg, FakeLLM(outputs(bad_claim=True))).research("SMPLALPHA", AS_OF)
    doc = session.get(ResearchReport, outcome.report_id).report_json
    bad = [c for c in doc["claims"] if not c["verified"]]
    assert len(bad) == 1 and any("E99" in p for p in bad[0]["problems"]) and any("45%" in p for p in bad[0]["problems"])
    assert doc["research_status"] == "partial"
    assert doc["conclusion"] == "potential_opportunity"  # an unverified material claim blocks "strong candidate"
    assert any("failed verification" in r for r in doc["conclusion_rationale"])


def test_llm_failure_still_produces_deterministic_report(session, providers, cfg, screened):
    outcome = service(session, providers, cfg, FakeLLM(error="rate_limited")).research("SMPLDELTA", AS_OF)
    doc = session.get(ResearchReport, outcome.report_id).report_json
    assert doc["research_status"] == "partial" and doc["company_overview"]["what_it_does"] is None
    assert doc["final_assessment"]["overall"]["classification"] == doc["conclusion"]  # still classified
    assert any("rate_limited" in x for x in doc["data_quality_limitations"])
    assert doc["financial_performance"]["headline_metrics"]["roe_latest"]["value"] > 0


def test_invalid_data_skips_llm(session, providers, cfg, screened):
    llm = FakeLLM(outputs())
    outcome = service(session, providers, cfg, llm).research("SMPLETA", AS_OF)
    assert llm.calls == []
    doc = session.get(ResearchReport, outcome.report_id).report_json
    assert doc["conclusion"] == "insufficient_evidence" and doc["research_status"] == "insufficient_data"


def test_announcements_are_wrapped_as_untrusted(session, providers, cfg, screened):
    llm = FakeLLM(outputs())
    service(session, providers, cfg, llm).research("SMPLZETA", AS_OF)
    user = llm.calls[0]["user"]
    assert '<untrusted_document evidence_id="E' in user and "Resignation of statutory auditor" in user
    assert "ignore them" in llm.calls[0]["system"]
    doc = session.query(ResearchReport).order_by(ResearchReport.id.desc()).first().report_json
    assert doc["conclusion"] == "high_risk"  # a serious governance flag is never averaged away
    assert doc["risks"]["red_flags"][0]["code"] == "auditor_resignation"
    assert doc["final_assessment"]["management_governance"]["rating"] == "Concerning"


def test_unknown_and_ambiguous_queries(session, providers, cfg, screened):
    svc = service(session, providers, cfg, FakeLLM())
    with pytest.raises(ResearchError, match="No listed company"):
        svc.research("NOSUCHCO", AS_OF)
    with pytest.raises(ResearchError, match="ambiguous"):
        svc.research("Ltd (SAMPLE)", AS_OF)
    with pytest.raises(ResearchError, match="ETF"):
        svc.research("SMPLNIFTYETF", AS_OF)


def test_watchlisted_company_gets_deduplicated_alerts(session, providers, cfg, screened):
    company = CompanyRepo(session).get_by_symbol("SMPLALPHA")
    wl = Watchlist(name="core")
    session.add(wl)
    session.flush()
    session.add(WatchlistCompany(watchlist_id=wl.id, company_id=company.id, thesis="compounder",
                                 invalidation_conditions=[{"metric": "roce_latest", "op": "<", "value": 0.9}]))  # fmt: skip
    session.commit()
    svc = service(session, providers, cfg, FakeLLM(outputs()))
    first = svc.research("SMPLALPHA", AS_OF)
    rules = sorted(a["rule_id"] for a in first.alerts)
    assert "thesis_review" in rules and "results_reminder" in rules
    entry = session.query(WatchlistCompany).one()
    assert entry.needs_review and entry.last_metrics
    svc.research("SMPLALPHA", AS_OF)
    assert session.query(Alert).count() == len(first.alerts)  # same events are not re-alerted


def test_fund_units_get_an_explanation_not_just_not_found(session, providers, cfg, screened):
    from datetime import date as d

    from app.models import DailyPrice

    session.add(DailyPrice(exchange="NSE", security_key="SILVERBEES", isin="INF204KC1402", series="EQ",
                           trade_date=d(2026, 10, 23), close=184.5, volume=1e6, traded_value=1.8e8))  # fmt: skip
    session.commit()
    with pytest.raises(ResearchError, match="fund unit"):
        service(session, providers, cfg, FakeLLM()).research("SILVERBEES", AS_OF)


def test_discovery_queue_shortlists_and_monitors(session, providers, cfg):
    from app.repos.watchlist_repo import WatchlistRepo
    from app.services.research.shortlist import shortlist

    run_screening(session, providers, cfg, AS_OF, enqueue_top_n=3)
    session.commit()
    out = service(session, providers, cfg, FakeLLM(outputs())).process_queue(3, 3, AS_OF)
    assert out.processed == 3 and out.succeeded == 3
    rows = shortlist(session, cfg)
    order = cfg.assessment.shortlist_classes
    assert [order.index(r.conclusion) for r in rows] == sorted(order.index(r.conclusion) for r in rows)
    wl = WatchlistRepo(session).get_by_name(cfg.assessment.auto_watchlist)
    monitored = {c.symbol for _, c in WatchlistRepo(session).entries(wl.id)} if wl else set()
    assert monitored == set(out.newly_monitored)
    assert "SMPLALPHA" in monitored  # strong candidates are monitored automatically
    entry = WatchlistRepo(session).entries(wl.id)[0][0]
    assert entry.needs_review and entry.invalidation_conditions and "Auto-added" in entry.thesis
    # a second pass never duplicates or overwrites entries
    from app.services.research.shortlist import monitor_if_shortlisted

    company = [c for _, c in WatchlistRepo(session).entries(wl.id)][0]
    assert monitor_if_shortlisted(session, company, {"conclusion": "strong_candidate"}, cfg, AS_OF) is False


def test_no_narrative_means_not_yet_a_strong_candidate(session, providers, cfg, screened):
    outcome = service(session, providers, cfg, FakeLLM(error="no_credentials")).research("SMPLALPHA", AS_OF)
    doc = session.get(ResearchReport, outcome.report_id).report_json
    assert doc["conclusion"] == "potential_opportunity"
    assert any("not been analysed" in r for r in doc["conclusion_rationale"])


def test_horizon_in_words_sets_the_headline(session, providers, cfg, screened):
    svc = service(session, providers, cfg, FakeLLM(outputs()))
    outcome = svc.research("Research SMPLALPHA for the next 2 years", AS_OF)
    doc = session.get(ResearchReport, outcome.report_id).report_json
    hz = doc["final_assessment"]["horizons"]
    assert doc["horizon"]["requested"] == "medium_term" and doc["horizon"]["primary"] == "medium_term"
    assert hz["medium_term"]["years"] == 2 and hz["long_term"]["years"] == 5
    assert doc["conclusion"] == hz["medium_term"]["classification"]
    assert list(doc["valuation"]["scenarios_by_horizon"]) == ["medium_term", "long_term"]
    assert doc["valuation"]["scenarios_by_horizon"]["medium_term"]["years"] == 2
    assert doc["valuation"]["fair_value_range"]["low"] <= doc["valuation"]["fair_value_range"]["high"]
    assert doc["valuation"]["medium_term_view"] == "Momentum steady."
    assert doc["growth_prospects"]["earnings_outlook"]["rating"]
    with pytest.raises(ResearchError, match="neither horizon"):
        svc.research("SMPLALPHA for 4 years", AS_OF)
