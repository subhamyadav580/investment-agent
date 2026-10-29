"""Provider interfaces. One implementation per external source; selected via registry.py."""

from datetime import date
from typing import Protocol

from app.schemas.market_data import (
    Announcement,
    CompanyProfile,
    FinancialStatements,
    PriceHistory,
    Shareholding,
    UniverseEntry,
)


class ProviderError(Exception):
    """Raised for transient/provider-side failures (timeouts, 5xx). Callers may retry."""


class DataNotAvailable(Exception):
    """Raised when the provider has no data for the requested company."""


class UniverseProvider(Protocol):
    name: str

    def load_universe(self) -> tuple[list[UniverseEntry], str]:
        """Returns (entries, universe_version). Version should identify the snapshot (e.g. content hash)."""
        ...


class FundamentalsProvider(Protocol):
    name: str

    def get_profile(self, symbol: str) -> CompanyProfile: ...

    def get_financials(self, symbol: str) -> FinancialStatements: ...

    def get_shareholding(self, symbol: str) -> list[Shareholding]: ...


class MarketDataProvider(Protocol):
    name: str

    def get_price_history(self, symbol: str, start: date, end: date) -> PriceHistory: ...


class AnnouncementsProvider(Protocol):
    name: str

    def get_announcements(self, symbol: str, since: date) -> list[Announcement]: ...
