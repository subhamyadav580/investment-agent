"""resolve_company: map a free-text name/ticker to exactly one exchange-listed company."""

from app.repos.company_repo import CompanyRepo
from app.repos.price_repo import PriceRepo
from app.services.data.normalization import normalize_symbol
from app.services.graph.deps import GraphDeps
from app.services.graph.state import ResearchState


def make_resolve_company(deps: GraphDeps):
    def resolve_company(state: ResearchState) -> dict:
        query = state["query"].strip()
        repo = CompanyRepo(deps.session)
        symbol = normalize_symbol(query)
        company = repo.get_by_symbol(symbol) or repo.get_by_alias(symbol)

        if company is None:
            # Not in the DB yet (universe never loaded, or a new listing): consult the universe provider.
            entries, _ = deps.providers.universe.load_universe()
            match = [e for e in entries if e.symbol == symbol or e.name.lower() == query.lower()]
            if len(match) == 1:
                company = repo.upsert_from_universe(match[0])
                repo.add_alias(company.id, match[0].symbol, "symbol")

        if company is None:
            candidates = repo.search_by_name(query)
            if len(candidates) == 1:
                company = candidates[0]
            elif candidates:
                options = ", ".join(f"{c.symbol} ({c.name})" for c in candidates)
                return {"errors": [f"'{query}' is ambiguous; did you mean one of: {options}"]}
            else:
                return {"errors": [_not_found_message(deps, query, symbol)]}

        if company.instrument_type != "EQUITY":
            return {"errors": [f"{company.symbol} is a {company.instrument_type}, not an operating company."]}
        return {
            "company_id": company.id,
            "symbol": company.symbol,
            "company_name": company.name,
            "exchange": company.exchange,
            "fetch_attempts": 0,
        }

    return resolve_company


def _not_found_message(deps: GraphDeps, query: str, symbol: str) -> str:
    """Explain *why* nothing was found when the symbol does trade (e.g. ETFs, which aren't companies)."""
    traded = PriceRepo(deps.session).latest_row(symbol)
    if traded is not None and (traded.isin or "").startswith("INF"):
        return (f"{symbol} trades on {traded.exchange}, but it is a fund unit (ETF/mutual fund, ISIN {traded.isin}), "
                "not an operating company. This tool researches companies only: ETFs have no revenue, profit or "
                "balance sheet to analyse.")  # fmt: skip
    if traded is not None:
        return (f"{symbol} trades on {traded.exchange} (series {traded.series}) but is not in the listed-company "
                "universe used for research (e.g. debt, REIT/InvIT or another non-equity instrument).")  # fmt: skip
    return f"No listed company found for '{query}'."
