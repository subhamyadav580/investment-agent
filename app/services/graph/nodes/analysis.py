"""LLM interpretation nodes: analyze_business, evaluate_valuation, analyze_risks.

Numbers are already computed; these nodes only interpret. Each returns None output on any LLM failure.
"""

from app.schemas.research import BusinessAnalysis, RiskAnalysis, ValuationCommentary
from app.services.graph.deps import GraphDeps
from app.services.graph.prompting import render_context, system_prompt
from app.services.graph.state import ResearchState
from app.services.research.metrics import historical_pe
from app.services.research.valuation import evaluate_valuation


def make_analyze_business(deps: GraphDeps):
    def analyze_business(state: ResearchState) -> dict:
        res = deps.llm.structured(
            task="business_analysis",
            system=system_prompt(deps.prompt_version, "business_analysis"),
            user=render_context(state, include_valuation=False),
            output_model=BusinessAnalysis,
        )
        return {"business": res.output, "llm_calls": [res.meta]}

    return analyze_business


def make_evaluate_valuation(deps: GraphDeps):
    def evaluate_valuation_node(state: ResearchState) -> dict:
        ev = state["evaluated"]
        data = ev.prepared.data
        hist = historical_pe(data.financials, data.prices) if data.financials and data.prices else {}
        valuation = evaluate_valuation(
            ev.prepared.metrics, hist, state["peer_comparison"].get("sector_medians"), state["sector_group"],
            data.financials.shares_outstanding_cr if data.financials else None,
        )  # fmt: skip
        state = {**state, "valuation": valuation}
        res = deps.llm.structured(
            task="valuation_commentary",
            system=system_prompt(deps.prompt_version, "valuation_commentary"),
            user=render_context(state),
            output_model=ValuationCommentary,
        )
        return {"valuation": valuation, "valuation_commentary": res.output, "llm_calls": [res.meta]}

    return evaluate_valuation_node


def make_analyze_risks(deps: GraphDeps):
    def analyze_risks(state: ResearchState) -> dict:
        res = deps.llm.structured(
            task="risk_analysis",
            system=system_prompt(deps.prompt_version, "risk_analysis"),
            user=render_context(state),
            output_model=RiskAnalysis,
        )
        return {"risk_analysis": res.output, "llm_calls": [res.meta]}

    return analyze_risks
