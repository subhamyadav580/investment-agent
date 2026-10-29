"""Import every ORM entity here so Base.metadata is complete for Alembic and create_all."""

from app.models.alert import Alert
from app.models.company import (
    Company,
    CompanyAlias,
    DailyPrice,
    FinancialSnapshot,
    MarketSnapshot,
    PriceFile,
    Source,
)
from app.models.research import ResearchReport, Watchlist, WatchlistCompany
from app.models.screening import ResearchQueueItem, ScreeningResult, ScreeningRun

__all__ = [
    "Alert",
    "Company",
    "CompanyAlias",
    "DailyPrice",
    "FinancialSnapshot",
    "MarketSnapshot",
    "PriceFile",
    "ResearchQueueItem",
    "ResearchReport",
    "ScreeningResult",
    "ScreeningRun",
    "Source",
    "Watchlist",
    "WatchlistCompany",
]
