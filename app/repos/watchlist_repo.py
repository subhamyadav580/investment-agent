from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Watchlist, WatchlistCompany


class WatchlistRepo:
    def __init__(self, session: Session):
        self.s = session

    def create(self, name: str) -> Watchlist:
        wl = Watchlist(name=name)
        self.s.add(wl)
        self.s.flush()
        return wl

    def get(self, watchlist_id: int) -> Watchlist | None:
        return self.s.get(Watchlist, watchlist_id)

    def get_by_name(self, name: str) -> Watchlist | None:
        return self.s.scalar(select(Watchlist).where(Watchlist.name == name))

    def list_all(self) -> list[Watchlist]:
        return list(self.s.scalars(select(Watchlist).order_by(Watchlist.id)))

    def entries(self, watchlist_id: int) -> list[tuple[WatchlistCompany, Company]]:
        q = (
            select(WatchlistCompany, Company)
            .join(Company, Company.id == WatchlistCompany.company_id)
            .where(WatchlistCompany.watchlist_id == watchlist_id)
            .order_by(Company.symbol)
        )
        return [(e, c) for e, c in self.s.execute(q).all()]

    def all_entries(self) -> list[tuple[WatchlistCompany, Company]]:
        q = select(WatchlistCompany, Company).join(Company, Company.id == WatchlistCompany.company_id)
        return [(e, c) for e, c in self.s.execute(q).all()]

    def entries_for_company(self, company_id: int) -> list[WatchlistCompany]:
        return list(self.s.scalars(select(WatchlistCompany).where(WatchlistCompany.company_id == company_id)))

    def get_entry(self, watchlist_id: int, company_id: int) -> WatchlistCompany | None:
        return self.s.scalar(
            select(WatchlistCompany).where(
                WatchlistCompany.watchlist_id == watchlist_id, WatchlistCompany.company_id == company_id
            )
        )

    def add_entry(self, entry: WatchlistCompany) -> WatchlistCompany:
        self.s.add(entry)
        self.s.flush()
        return entry

    def delete_entry(self, entry: WatchlistCompany) -> None:
        self.s.delete(entry)
