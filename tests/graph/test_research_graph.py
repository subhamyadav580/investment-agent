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
        BusinessAnalysis: BusinessAnalysis(business_overview="Makes machines.", competitive_position="Strong returns.",
                                           financial_trends="Steady growth.", claims=claims,
                                           open_questions=["Order book?"]),  # fmt: skip
        ValuationCommentary: ValuationCommentary(summary="In line with history.", claims=[]),
        RiskAnalysis: RiskAnalysis(
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
    assert doc["conclusion"] == "worth_deeper_research"
    assert all(c["verified"] for c in doc["claims"])
    assert doc["business_overview"] == "Makes machines."
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
    assert doc["conclusion"] == "watch"


def test_llm_failure_still_produces_deterministic_report(session, providers, cfg, screened):
    outcome = service(session, providers, cfg, FakeLLM(error="rate_limited")).research("SMPLDELTA", AS_OF)
    doc = session.get(ResearchReport, outcome.report_id).report_json
    assert doc["research_status"] == "partial" and doc["business_overview"] is None
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
    assert doc["conclusion"] == "watch"  # governance review caps the conclusion


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
