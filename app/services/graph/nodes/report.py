"""verify_evidence, generate_report, persist_report, evaluate_alerts."""

from datetime import date

from app.models import ResearchReport
from app.repos.company_repo import CompanyRepo
from app.repos.report_repo import ReportRepo
from app.repos.watchlist_repo import WatchlistRepo
from app.schemas.research import ResearchReportDoc, VerifiedClaim
from app.schemas.screening import Metric
from app.services.alerts.alert_service import evaluate_watchlist_entry
from app.services.graph.deps import GraphDeps
from app.services.graph.state import ResearchState
from app.services.research.assessment import LABELS, AssessmentInputs, build_assessment
from app.services.research.evidence import numeric_leaves, verify_claims, verify_risks

ANNUAL_TABLE_METRICS = ("revenue", "operating_profit", "net_profit", "cfo", "total_debt", "total_equity",
                        "net_interest_income", "gross_npa_pct")  # fmt: skip
HEADLINE_METRICS = (
    "history_years", "revenue_cagr", "profit_cagr", "revenue_cagr_long", "profit_cagr_long", "revenue_growth_latest",
    "profit_growth_latest", "operating_margin_latest", "operating_margin_avg", "net_margin_latest", "roce_latest",
    "roce_avg_3y", "roe_latest", "roe_avg_3y", "roa_latest", "debt_to_equity", "net_debt_to_ebitda",
    "interest_coverage", "cfo_to_pat_3y", "receivable_days_latest", "gross_npa_pct", "net_npa_pct",
    "capital_adequacy_ratio", "profit_positive_ratio",
)  # fmt: skip
MOMENTUM_METRICS = ("revenue_growth_q_yoy", "profit_growth_q_yoy", "profit_growth_q_yoy_prev", "revenue_growth_latest",
                    "profit_growth_latest")  # fmt: skip
OWNERSHIP_METRICS = ("promoter_holding_pct", "promoter_pledged_pct", "promoter_holding_change_1y")
GROWTH_CATEGORIES = ("order_win", "acquisition", "capacity_expansion", "credit_rating_upgrade")
NOT_COVERED = [
    "Related-party transactions are not in the structured data; read the related-party note in the annual report.",
    "Management quality beyond what filings and numbers show (track record, succession) needs your own reading.",
]


def make_verify_evidence(deps: GraphDeps):
    def verify_evidence(state: ResearchState) -> dict:
        metrics = {k: Metric(**m) for k, m in state["metrics"].items()}
        known = {e["id"] for e in state["evidence"]}
        refs = numeric_leaves([state.get("valuation"), state.get("peer_comparison"), state.get("industry_trend"),
                               [r.threshold for r in state["evaluated"].rules]])  # fmt: skip
        claims: list[VerifiedClaim] = []
        if b := state.get("business"):
            claims += verify_claims("business", b.claims, known, metrics, refs)
        if v := state.get("valuation_commentary"):
            claims += verify_claims("valuation", v.claims, known, metrics, refs)
        if r := state.get("risk_analysis"):
            claims += verify_risks(r.risks, known, metrics, refs)
        return {"verified_claims": [c.model_dump() for c in claims]}

    return verify_evidence


def _default_invalidation(state: ResearchState, deps: GraphDeps) -> list[str]:
    q = deps.cfg.quality
    if state["sector_group"] == "financial":
        return [f"ROE below {q.min_roe_financial:.0%} for two consecutive years.",
                f"Gross NPA above {q.max_gross_npa_pct:.1f}%.", "Any serious governance disclosure."]  # fmt: skip
    return [
        f"ROCE below {q.min_roce:.0%} for two consecutive years.",
        f"Debt/equity above {q.max_debt_to_equity:.1f}x or interest coverage below {q.min_interest_coverage:.1f}x.",
        f"3-year operating cash flow below {q.min_cfo_to_pat:.0%} of reported profit.",
        "Any serious governance disclosure (auditor resignation/qualification, regulatory order).",
    ]


def _assessment(state: ResearchState, deps: GraphDeps, unverified_material: int) -> dict:
    ev = state["evaluated"]
    data = ev.prepared.data
    inputs = AssessmentInputs(
        sector_group=state["sector_group"], metrics=ev.prepared.metrics, values=ev.values,
        dimension_scores=ev.evaluation.dimension_scores, missing_components=ev.evaluation.missing_components,
        score=ev.evaluation.score, flags=ev.flags, rules=ev.rules, data_quality=state["data_quality"],
        valuation=state.get("valuation") or {}, unverified_material=unverified_material,
        financial_source_keys=list(data.financials.sources) if data.financials else [],
        price_source_keys=[data.prices.source.key] if data.prices and data.prices.source else [],
        shareholding_source_keys=[h.source.key for h in data.shareholding],
        narrative_available=state.get("business") is not None,
        horizon_scores=ev.evaluation.horizon_scores, medium_term_scores=ev.evaluation.medium_term_scores,
        medium_term_missing=ev.evaluation.medium_term_missing, earnings_basis=ev.evaluation.earnings_basis,
        catalysts=ev.evaluation.catalysts, primary_horizon=_primary(state),
        horizon_years=state.get("horizon_years") or {"long_term": 5, "medium_term": 2},
    )  # fmt: skip
    evidence_id_for = {key: eid for eid, key in state["evidence_key_by_id"].items()}
    return build_assessment(inputs, deps.cfg, evidence_id_for)


def _primary(state: ResearchState) -> str:
    return "medium_term" if state.get("horizon") == "medium_term" else "long_term"


def _pick(state: ResearchState, keys: tuple[str, ...]) -> dict:
    return {k: state["metrics"][k] for k in keys if k in state["metrics"]}


def make_generate_report(deps: GraphDeps):
    def generate_report(state: ResearchState) -> dict:
        ev = state["evaluated"]
        dq = state["data_quality"]
        data = ev.prepared.data
        evaluation = ev.evaluation
        business, valuation_c, risks = state.get("business"), state.get("valuation_commentary"), state.get("risk_analysis")
        claims = [VerifiedClaim(**c) for c in state.get("verified_claims", [])]
        unverified_material = sum(1 for c in claims if not c.verified and c.materiality == "material")
        assessment = _assessment(state, deps, unverified_material)
        overall = assessment["overall"]
        conclusion = overall["classification"]

        llm_failures = [f"{c['task']}: {c['error']}" for c in state.get("llm_calls", []) if c.get("error")]
        limitations = [f"{i.severity}: {i.message}" for i in dq.issues if i.severity in ("error", "warning", "info")]
        limitations += (state.get("valuation") or {}).get("limitations", [])
        if llm_failures:
            limitations.append("Narrative analysis unavailable for: " + "; ".join(llm_failures))
        if unverified_material:
            limitations.append(f"{unverified_material} material claim(s) failed verification; see `claims`.")

        if not dq.is_eligible:
            status = "insufficient_data"
        elif llm_failures or unverified_material or dq.score < 80:
            status = "partial"
        else:
            status = "complete"

        fin = data.financials
        annual = {}
        if fin:
            annual = {m: fin.series(m) for m in ANNUAL_TABLE_METRICS if any(v.metric == m for v in fin.values)}
        as_of = date.fromisoformat(state["as_of_date"])
        upcoming = [f"{a.title} on {a.event_date}" for a in data.announcements if a.event_date and a.event_date >= as_of]
        key_to_id = {key: eid for eid, key in state["evidence_key_by_id"].items()}
        growth_filings = [{"date": a.published_at.date().isoformat(), "category": a.category, "title": a.title,
                           "evidence_id": key_to_id.get(a.source.key)}
                          for a in data.announcements if a.category in GROWTH_CATEGORIES]  # fmt: skip
        ratings = {k: assessment[k]["rating"] for k in ("business_quality", "financial_health",
                                                         "management_governance", "valuation", "data_quality")}  # fmt: skip
        hz = assessment["horizons"]
        horizon_line = " ".join(f"{h['horizon_label']} ({h['years']}y): {h['label']}." for h in hz.values())
        summary = (
            f"{state['company_name']} ({state['symbol']}): {horizon_line} "
            f"Business quality {ratings['business_quality']}, financial health {ratings['financial_health']}, "
            f"management and governance {ratings['management_governance']}, valuation {ratings['valuation']}, "
            f"data quality {ratings['data_quality']}. Scores: "
            + ", ".join(f"{h['horizon_label'].lower()} {h['score'] if h['score'] is not None else 'n/a'}/100"
                        for h in hz.values())
            + f" under rules {deps.cfg.version}; {len(assessment['red_flags'])} red flag(s)."
        )  # fmt: skip
        trend = state.get("industry_trend")

        doc = ResearchReportDoc(
            symbol=state["symbol"], name=state["company_name"], exchange=state["exchange"], sector=state.get("sector"),
            industry=state.get("industry"), as_of_date=as_of, research_status=status, executive_summary=summary,
            screening_score=evaluation.score, dimension_scores=evaluation.dimension_scores,
            score_weights=deps.cfg.scoring.weights_for(state["sector_group"]),
            horizon={"requested": state.get("horizon") or "long_term", "primary": overall["horizon"],
                     "years": state.get("horizon_years") or {}, "medium_term_weights": deps.cfg.horizons.medium_term.weights},
            company_overview={
                "what_it_does": business.business_overview if business else None,
                "revenue_model": business.revenue_model if business else None,
                "competitive_advantages": business.competitive_advantages if business else [],
                "competitive_position": business.competitive_position if business else None,
            },
            financial_performance={
                "years_covered": dq.years_available,
                "headline_metrics": _pick(state, HEADLINE_METRICS),
                "annual_inr_crore": annual,
                "commentary": business.financial_trends if business else None,
                "rules": [r.model_dump() for r in ev.rules],
                "missing_score_components": evaluation.missing_components,
            },
            peer_comparison=state.get("peer_comparison") or {},
            valuation={
                **(state.get("valuation") or {}),
                "commentary": valuation_c.summary if valuation_c else None,
                "scenario_commentary": valuation_c.scenario_commentary if valuation_c else None,
                "medium_term_view": valuation_c.medium_term_view if valuation_c else None,
            },
            management_governance={
                "promoter": _pick(state, OWNERSHIP_METRICS),
                "shareholding_history": [h.model_dump(mode="json", exclude={"source"}) for h in data.shareholding[-8:]],
                "flags": [f.model_dump() for f in ev.flags],
                "capital_allocation": _pick(state, ("return_on_incremental_capital", "cfo_to_pat_3y", "debt_to_equity")),
                "commentary": risks.management_assessment if risks else None,
                "not_covered": NOT_COVERED,
            },
            growth_prospects={
                "industry_outlook": business.industry_outlook if business else None,
                "industry_trend": trend,
                "recent_momentum": _pick(state, MOMENTUM_METRICS),
                "earnings_outlook": hz.get("medium_term", {}).get("earnings_outlook"),
                "catalysts": hz.get("medium_term", {}).get("catalysts"),
                "growth_drivers": business.growth_drivers if business else [],
                "growth_filings": growth_filings,
                "competitive_threats": business.competitive_threats if business else [],
            },
            risks={
                "red_flags": assessment["red_flags"],
                "items": [r.model_dump() for r in risks.risks] if risks else [],
                "downside_scenarios": risks.downside_scenarios if risks else [],
                "invalidation_conditions": (risks.invalidation_conditions if risks else [])
                + _default_invalidation(state, deps),
            },
            final_assessment={k: v for k, v in assessment.items() if k != "red_flags"},
            conclusion=conclusion,
            conclusion_label=LABELS[conclusion],
            conclusion_rationale=overall["reasons"],
            monitor_next=(risks.monitor_next if risks else []) + upcoming,
            catalysts=risks.catalysts if risks else [],
            open_questions=business.open_questions if business else [],
            evidence=state["evidence"],
            claims=claims,
            data_quality_limitations=limitations,
        )  # fmt: skip
        return {"report": doc.model_dump(mode="json")}

    return generate_report


def make_persist_report(deps: GraphDeps):
    def persist_report(state: ResearchState) -> dict:
        calls = state.get("llm_calls", [])
        usage = {
            "calls": len(calls),
            "failed": sum(1 for c in calls if c.get("error")),
            "input_tokens": sum(c.get("input_tokens") or 0 for c in calls),
            "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
            "detail": calls,
        }
        report = ReportRepo(deps.session).add(
            ResearchReport(
                company_id=state["company_id"],
                as_of_date=date.fromisoformat(state["as_of_date"]),
                status=state["report"]["research_status"],
                conclusion=state["report"]["conclusion"],
                report_json=state["report"],
                metrics_json=state["evaluated"].values,
                model_version=deps.llm.model_version if usage["calls"] else None,
                prompt_version=deps.prompt_version,
                rules_version=deps.cfg.version,
                source_snapshot=[{"key": k, "source_id": v} for k, v in sorted(state.get("source_ids", {}).items())],
                llm_usage=usage,
            )
        )
        return {"report_id": report.id}

    return persist_report


def make_evaluate_alerts(deps: GraphDeps):
    def evaluate_alerts(state: ResearchState) -> dict:
        if not state["data_quality"].is_eligible:
            return {"alerts": []}
        company = CompanyRepo(deps.session).get(state["company_id"])
        alerts = []
        for entry in WatchlistRepo(deps.session).entries_for_company(company.id):
            alerts += evaluate_watchlist_entry(
                deps.session, company, entry, state["evaluated"], date.fromisoformat(state["as_of_date"]), deps.cfg,
                quiet_hours=deps.quiet_hours, report_base_url=deps.report_base_url,
            )  # fmt: skip
        return {"alerts": [{"id": a.id, "rule_id": a.rule_id, "severity": a.severity} for a in alerts]}

    return evaluate_alerts
