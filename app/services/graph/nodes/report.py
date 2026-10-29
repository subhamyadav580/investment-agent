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
from app.services.research.evidence import numeric_leaves, verify_claims, verify_risks

ANNUAL_TABLE_METRICS = ("revenue", "operating_profit", "net_profit", "cfo", "total_debt", "total_equity",
                        "net_interest_income", "gross_npa_pct")  # fmt: skip
HEADLINE_METRICS = (
    "revenue_cagr", "profit_cagr", "operating_margin_latest", "operating_margin_avg", "net_margin_latest",
    "roce_latest", "roce_avg_3y", "roe_latest", "roa_latest", "debt_to_equity", "interest_coverage",
    "cfo_to_pat_3y", "receivable_days_latest", "gross_npa_pct", "capital_adequacy_ratio", "profit_positive_ratio",
)  # fmt: skip


def make_verify_evidence(deps: GraphDeps):
    def verify_evidence(state: ResearchState) -> dict:
        metrics = {k: Metric(**m) for k, m in state["metrics"].items()}
        known = {e["id"] for e in state["evidence"]}
        refs = numeric_leaves([state.get("valuation"), state.get("peer_comparison"),
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


def _conclusion(state: ResearchState, deps: GraphDeps, unverified_material: int) -> tuple[str, list[str]]:
    dq = state["data_quality"]
    ev = state["evaluated"].evaluation
    if not dq.is_eligible:
        return "insufficient_evidence", [f"Data failed validation: {i.message}" for i in dq.errors]
    rationale = [f"Research-priority score {ev.score}/100 under rules {deps.cfg.version}."]
    if ev.status == "governance_review":
        return "watch", rationale + ["Serious governance flags need separate human review first:"] + ev.exclusion_reasons
    if ev.status == "rejected":
        return "watch", rationale + ["Failed a hard screening rule:"] + ev.exclusion_reasons
    warnings = [f for f in state["evaluated"].flags if f.severity == "warning"]
    if warnings:
        rationale.append("Governance warnings to investigate: " + "; ".join(f.message for f in warnings))
    if unverified_material:
        rationale.append(f"{unverified_material} material analytical claim(s) could not be verified.")
    if ev.score is not None and ev.score >= deps.cfg.research.worth_deeper_research_score and not unverified_material:
        return "worth_deeper_research", rationale + ["Passes all hard rules and scores above the research threshold."]
    return "watch", rationale + ["Below the deeper-research threshold or has unresolved verification gaps."]


def make_generate_report(deps: GraphDeps):
    def generate_report(state: ResearchState) -> dict:
        ev = state["evaluated"]
        dq = state["data_quality"]
        evaluation = ev.evaluation
        business, valuation_c, risks = state.get("business"), state.get("valuation_commentary"), state.get("risk_analysis")
        claims = [VerifiedClaim(**c) for c in state.get("verified_claims", [])]
        unverified_material = sum(1 for c in claims if not c.verified and c.materiality == "material")
        conclusion, rationale = _conclusion(state, deps, unverified_material)

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

        fin = ev.prepared.data.financials
        annual = {}
        if fin:
            annual = {m: fin.series(m) for m in ANNUAL_TABLE_METRICS if any(v.metric == m for v in fin.values)}
        dims = evaluation.dimension_scores
        ranked_dims = sorted(dims.items(), key=lambda kv: -kv[1])
        summary = (
            f"{state['company_name']} ({state['symbol']}): research-priority score "
            f"{evaluation.score if evaluation.score is not None else 'n/a'}/100, screening status "
            f"'{evaluation.status}'. "
            + (f"Strongest dimension: {ranked_dims[0][0]} ({ranked_dims[0][1]}); weakest: {ranked_dims[-1][0]} "
               f"({ranked_dims[-1][1]}). " if ranked_dims else "")
            + f"{len(ev.flags)} governance flag(s). Data quality {dq.score}/100 over {dq.years_available} year(s). "
            f"Conclusion: {conclusion.replace('_', ' ')}."
        )  # fmt: skip
        upcoming = [f"{a.title} on {a.event_date}" for a in ev.prepared.data.announcements
                    if a.event_date and a.event_date >= date.fromisoformat(state["as_of_date"])]  # fmt: skip

        doc = ResearchReportDoc(
            symbol=state["symbol"], name=state["company_name"], exchange=state["exchange"], sector=state.get("sector"),
            as_of_date=date.fromisoformat(state["as_of_date"]), research_status=status, executive_summary=summary,
            screening_score=evaluation.score, dimension_scores=dims,
            business_overview=business.business_overview if business else None,
            competitive_position=business.competitive_position if business else None,
            financial_performance={
                "headline_metrics": {k: state["metrics"][k] for k in HEADLINE_METRICS if k in state["metrics"]},
                "annual_inr_crore": annual,
                "rules": [r.model_dump() for r in ev.rules],
                "missing_score_components": evaluation.missing_components,
            },
            financial_commentary=business.financial_trends if business else None,
            valuation=state.get("valuation") or {},
            valuation_commentary=valuation_c.summary if valuation_c else None,
            peer_comparison=state.get("peer_comparison") or {},
            risks=[r.model_dump() for r in risks.risks] if risks else [],
            downside_scenarios=risks.downside_scenarios if risks else [],
            governance={
                "flags": [f.model_dump() for f in ev.flags],
                "latest_shareholding": ev.prepared.data.shareholding[-1].model_dump(mode="json", exclude={"source"})
                if ev.prepared.data.shareholding else None,
            },  # fmt: skip
            monitor_next=(risks.monitor_next if risks else []) + upcoming,
            catalysts=risks.catalysts if risks else [],
            evidence=state["evidence"],
            claims=claims,
            data_quality_limitations=limitations,
            invalidation_conditions=(risks.invalidation_conditions if risks else []) + _default_invalidation(state, deps),
            conclusion=conclusion,
            conclusion_rationale=rationale,
            open_questions=business.open_questions if business else [],
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
