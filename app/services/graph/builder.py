"""Research graph (plan 6.1):

    resolve_company -> fetch_company_data -(transient failure, retry)-> fetch_company_data
                                          -> validate_data -> calculate_metrics
    calculate_metrics -(invalid data)-> generate_report          (no LLM spend on unusable data)
                      -(valid)-> analyze_business -> evaluate_valuation -> analyze_risks -> verify_evidence
                                 -> generate_report
    generate_report -> persist_report -> evaluate_alerts -> END

There are no tools in this graph that can place orders, and the LLM never sees credentials.
"""

from langgraph.graph import END, START, StateGraph

from app.services.graph.deps import GraphDeps
from app.services.graph.nodes.analysis import (
    make_analyze_business,
    make_analyze_risks,
    make_evaluate_valuation,
)
from app.services.graph.nodes.data import make_fetch_company_data, make_validate_data, should_retry_fetch
from app.services.graph.nodes.metrics_node import make_calculate_metrics, route_after_metrics
from app.services.graph.nodes.report import (
    make_evaluate_alerts,
    make_generate_report,
    make_persist_report,
    make_verify_evidence,
)
from app.services.graph.nodes.resolve import make_resolve_company
from app.services.graph.state import ResearchState


def build_research_graph(deps: GraphDeps):
    g = StateGraph(ResearchState)
    g.add_node("resolve_company", make_resolve_company(deps))
    g.add_node("fetch_company_data", make_fetch_company_data(deps))
    g.add_node("validate_data", make_validate_data(deps))
    g.add_node("calculate_metrics", make_calculate_metrics(deps))
    g.add_node("analyze_business", make_analyze_business(deps))
    g.add_node("evaluate_valuation", make_evaluate_valuation(deps))
    g.add_node("analyze_risks", make_analyze_risks(deps))
    g.add_node("verify_evidence", make_verify_evidence(deps))
    g.add_node("generate_report", make_generate_report(deps))
    g.add_node("persist_report", make_persist_report(deps))
    g.add_node("evaluate_alerts", make_evaluate_alerts(deps))

    g.add_edge(START, "resolve_company")
    g.add_conditional_edges(
        "resolve_company", lambda s: "fetch" if s.get("company_id") else "stop", {"fetch": "fetch_company_data", "stop": END}
    )
    g.add_conditional_edges(
        "fetch_company_data", should_retry_fetch(deps), {"retry": "fetch_company_data", "validate": "validate_data"}
    )
    g.add_edge("validate_data", "calculate_metrics")
    g.add_conditional_edges(
        "calculate_metrics", route_after_metrics, {"analyze": "analyze_business", "report": "generate_report"}
    )
    g.add_edge("analyze_business", "evaluate_valuation")
    g.add_edge("evaluate_valuation", "analyze_risks")
    g.add_edge("analyze_risks", "verify_evidence")
    g.add_edge("verify_evidence", "generate_report")
    g.add_edge("generate_report", "persist_report")
    g.add_edge("persist_report", "evaluate_alerts")
    g.add_edge("evaluate_alerts", END)
    return g.compile()
