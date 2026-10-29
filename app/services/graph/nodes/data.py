"""fetch_company_data + validate_data."""

from datetime import date

from app.repos.company_repo import CompanyRepo
from app.services.data.freshness import validate_company_data
from app.services.data.identity import provider_symbol
from app.services.discovery.data_enrichment import apply_profile, fetch_company_data, persist_company_data
from app.services.graph.deps import GraphDeps
from app.services.graph.state import ResearchState


def make_fetch_company_data(deps: GraphDeps):
    def fetch(state: ResearchState) -> dict:
        as_of = date.fromisoformat(state["as_of_date"])
        company = CompanyRepo(deps.session).get(state["company_id"])
        data = fetch_company_data(deps.providers, provider_symbol(company), as_of)
        group = apply_profile(company, data.profile)
        source_ids = persist_company_data(deps.session, company, data)
        return {
            "data": data,
            "sector": company.sector,
            "sector_group": group,
            "source_ids": source_ids,
            "fetch_attempts": state.get("fetch_attempts", 0) + 1,
            "errors": [f"fetch: {e}" for e in data.fetch_errors],
        }

    return fetch


def should_retry_fetch(deps: GraphDeps):
    def route(state: ResearchState) -> str:
        data = state["data"]
        transient = bool(data.fetch_errors) and data.financials is None
        return "retry" if transient and state["fetch_attempts"] < deps.max_fetch_attempts else "validate"

    return route


def make_validate_data(deps: GraphDeps):
    def validate(state: ResearchState) -> dict:
        dq = validate_company_data(
            state["data"], state["sector_group"], date.fromisoformat(state["as_of_date"]), deps.cfg.eligibility
        )
        return {"data_quality": dq}

    return validate
