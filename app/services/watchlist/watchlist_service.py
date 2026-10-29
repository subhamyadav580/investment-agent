"""Watchlists and per-company investment theses."""

from sqlalchemy.orm import Session

from app.models import Company, Watchlist, WatchlistCompany
from app.repos.company_repo import CompanyRepo
from app.repos.watchlist_repo import WatchlistRepo
from app.schemas.watchlist import WatchlistCompanyIn
from app.services.data.normalization import normalize_symbol
from app.services.data.providers.base import UniverseProvider


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class WatchlistService:
    def __init__(self, session: Session, universe: UniverseProvider):
        self.s = session
        self.repo = WatchlistRepo(session)
        self.companies = CompanyRepo(session)
        self.universe = universe

    def create(self, name: str) -> Watchlist:
        if self.repo.get_by_name(name):
            raise Conflict(f"watchlist '{name}' already exists")
        return self.repo.create(name)

    def get(self, watchlist_id: int) -> tuple[Watchlist, list[tuple[WatchlistCompany, Company]]]:
        wl = self.repo.get(watchlist_id)
        if wl is None:
            raise NotFound(f"watchlist {watchlist_id} not found")
        return wl, self.repo.entries(watchlist_id)

    def list_all(self) -> list[tuple[Watchlist, list[tuple[WatchlistCompany, Company]]]]:
        return [(wl, self.repo.entries(wl.id)) for wl in self.repo.list_all()]

    def _resolve(self, symbol: str) -> Company:
        sym = normalize_symbol(symbol)
        company = self.companies.get_by_symbol(sym) or self.companies.get_by_alias(sym)
        if company is None:
            entries, _ = self.universe.load_universe()
            match = next((e for e in entries if e.symbol == sym), None)
            if match is None:
                raise NotFound(f"no listed company with symbol {sym}")
            company = self.companies.upsert_from_universe(match)
        if company.instrument_type != "EQUITY":
            raise Conflict(f"{sym} is a {company.instrument_type}, not an operating company")
        return company

    def upsert_company(self, watchlist_id: int, body: WatchlistCompanyIn) -> tuple[WatchlistCompany, Company]:
        if self.repo.get(watchlist_id) is None:
            raise NotFound(f"watchlist {watchlist_id} not found")
        company = self._resolve(body.symbol)
        entry = self.repo.get_entry(watchlist_id, company.id) or self.repo.add_entry(
            WatchlistCompany(watchlist_id=watchlist_id, company_id=company.id)
        )
        entry.thesis = body.thesis
        entry.assumptions = body.assumptions
        entry.invalidation_conditions = [c.model_dump() for c in body.invalidation_conditions]
        entry.alert_overrides = body.alert_overrides
        entry.valuation_range = body.valuation_range.model_dump() if body.valuation_range else None
        entry.review_date = body.review_date
        entry.needs_review = False  # an edited thesis has been reviewed
        self.s.flush()
        return entry, company

    def remove_company(self, watchlist_id: int, symbol: str) -> None:
        company = self.companies.get_by_symbol(normalize_symbol(symbol))
        entry = self.repo.get_entry(watchlist_id, company.id) if company else None
        if entry is None:
            raise NotFound(f"{symbol} is not on watchlist {watchlist_id}")
        self.repo.delete_entry(entry)
