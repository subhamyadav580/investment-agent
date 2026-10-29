from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Company, CompanyAlias
from app.schemas.market_data import UniverseEntry


class CompanyRepo:
    def __init__(self, session: Session):
        self.s = session

    def get(self, company_id: int) -> Company | None:
        return self.s.get(Company, company_id)

    def get_by_symbol(self, symbol: str, exchange: str = "NSE") -> Company | None:
        return self.s.scalar(select(Company).where(Company.symbol == symbol, Company.exchange == exchange))

    def get_by_isin(self, isin: str) -> Company | None:
        return self.s.scalar(select(Company).where(Company.isin == isin))

    def get_by_alias(self, alias: str) -> Company | None:
        return self.s.scalar(
            select(Company).join(CompanyAlias, CompanyAlias.company_id == Company.id).where(
                func.upper(CompanyAlias.alias) == alias.upper()
            )
        )

    def search_by_name(self, text: str, limit: int = 5) -> list[Company]:
        pattern = f"%{text.lower()}%"
        return list(
            self.s.scalars(
                select(Company)
                .where(or_(func.lower(Company.name).like(pattern), func.lower(Company.symbol).like(pattern)))
                .where(Company.is_active.is_(True))
                .order_by(Company.symbol)
                .limit(limit)
            )
        )

    def list_by_ids(self, ids: list[int]) -> dict[int, Company]:
        if not ids:
            return {}
        return {c.id: c for c in self.s.scalars(select(Company).where(Company.id.in_(ids)))}

    def upsert_from_universe(self, entry: UniverseEntry) -> Company:
        company = self.get_by_symbol(entry.symbol, entry.exchange)
        if company is None:
            company = Company(symbol=entry.symbol, exchange=entry.exchange)
            self.s.add(company)
        company.name = entry.name
        company.isin = entry.isin or company.isin
        company.bse_code = entry.bse_code or company.bse_code
        company.series = entry.series
        company.instrument_type = entry.instrument_type
        company.is_sme = entry.is_sme
        company.listed_on = entry.listed_on
        company.is_active = True
        self.s.flush()
        return company

    def add_alias(self, company_id: int, alias: str, alias_type: str) -> None:
        exists = self.s.scalar(
            select(CompanyAlias).where(
                CompanyAlias.company_id == company_id, CompanyAlias.alias == alias, CompanyAlias.alias_type == alias_type
            )
        )
        if not exists:
            self.s.add(CompanyAlias(company_id=company_id, alias=alias, alias_type=alias_type))

    def mark_inactive_except(self, exchange: str, active_ids: set[int]) -> int:
        stale = self.s.scalars(
            select(Company).where(Company.exchange == exchange, Company.is_active.is_(True), Company.id.not_in(active_ids))
        ).all()
        for c in stale:
            c.is_active = False
        return len(stale)
