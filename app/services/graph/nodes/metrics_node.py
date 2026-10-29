"""calculate_metrics: deterministic metrics, rules, score, peer table, and the evidence registry."""

from datetime import date

from app.repos.screening_repo import ScreeningRepo
from app.services.discovery.company_evaluator import PreparedCompany, evaluate
from app.services.graph.deps import GraphDeps
from app.services.graph.state import ResearchState
from app.services.research.evidence import build_evidence
from app.services.research.metrics import compute_metrics
from app.services.research.peer_comparison import compare_to_peers


def _peer_values(deps: GraphDeps, sector: str | None) -> tuple[dict[str, dict], dict[str, float] | None]:
    """Peer metric values + sector medians from the latest completed screening run."""
    repo = ScreeningRepo(deps.session)
    run = repo.latest_completed_run()
    if run is None or not sector:
        return {}, None
    peers = {
        c.symbol: r.metrics
        for r, c in repo.results_for_run(run.id)
        if c.sector == sector and r.status not in ("ineligible", "excluded_instrument")
    }
    return peers, (run.summary or {}).get("sector_medians", {}).get(sector)


def make_calculate_metrics(deps: GraphDeps):
    def calculate_metrics(state: ResearchState) -> dict:
        as_of = date.fromisoformat(state["as_of_date"])
        metrics = compute_metrics(state["data"], state["sector_group"], as_of)
        prepared = PreparedCompany(
            state["symbol"], state.get("sector"), state["sector_group"], state["data"], state["data_quality"], metrics
        )
        peers, medians = _peer_values(deps, state.get("sector"))
        evaluated = evaluate(prepared, medians, as_of, deps.cfg)
        evidence, key_by_id = build_evidence(state["data"].all_sources())
        return {
            "evaluated": evaluated,
            "metrics": {k: m.model_dump() for k, m in metrics.items()},
            "peer_comparison": {**compare_to_peers(state["symbol"], evaluated.values, peers), "sector_medians": medians},
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "evidence_key_by_id": key_by_id,
        }

    return calculate_metrics


def route_after_metrics(state: ResearchState) -> str:
    # Never spend LLM calls interpreting data that failed validation: go straight to an honest report.
    return "analyze" if state["data_quality"].is_eligible else "report"
