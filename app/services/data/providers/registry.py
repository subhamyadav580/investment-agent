"""Strategy + Factory: maps configured provider names to implementations, per data capability.

Adding a provider (e.g. Kite Connect for prices) = one new module in this package + one branch below.
"""

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.infra.http_client import PoliteHttpClient
from app.services.data.providers.base import (
    AnnouncementsProvider,
    FundamentalsProvider,
    MarketDataProvider,
    UniverseProvider,
)
from app.services.data.providers.exchange_prices_provider import ExchangePricesProvider
from app.services.data.providers.fixture_provider import FixtureProvider
from app.services.data.providers.local_files_provider import LocalFilesProvider
from app.services.data.providers.nse_announcements_provider import NseAnnouncementsProvider
from app.services.data.providers.nse_universe_provider import ExchangeUniverseProvider, NseCsvUniverseProvider
from app.services.data.providers.screener_provider import ScreenerProvider


@dataclass(frozen=True)
class Providers:
    universe: UniverseProvider
    fundamentals: FundamentalsProvider
    market_data: MarketDataProvider
    announcements: AnnouncementsProvider


def build_http_client(settings: Settings) -> PoliteHttpClient:
    return PoliteHttpClient(
        user_agent=settings.http_user_agent,
        cache_dir=settings.http_cache_dir,
        min_interval_seconds=settings.http_min_interval_seconds,
        host_intervals={"www.screener.in": settings.screener_min_interval_seconds},
        timeout=settings.provider_timeout_seconds,
    )


class _Factory:
    def __init__(self, settings: Settings, http: PoliteHttpClient | None, session_factory):
        self.settings = settings
        self._http = http
        self._session_factory = session_factory
        self.cache: dict[str, object] = {}

    @property
    def http(self) -> PoliteHttpClient:
        if self._http is None:
            self._http = build_http_client(self.settings)
        return self._http

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            from app.db.session import get_session_factory

            self._session_factory = get_session_factory()
        return self._session_factory

    def build(self, name: str, capability: str):
        key = f"{name}:{capability}" if name == "nse_csv" else name
        if key in self.cache:
            return self.cache[key]
        s = self.settings
        match name, capability:
            case "fixture", _:
                impl = FixtureProvider(s.fixture_path)
            case "local_files", _:
                impl = LocalFilesProvider(s.local_data_dir)
            case "nse_csv", "universe":
                impl = NseCsvUniverseProvider(s.nse_equity_list_url, s.nse_equity_list_path, s.provider_timeout_seconds)
            case "nse_bse", "universe":
                impl = ExchangeUniverseProvider(self.http, s.nse_equity_list_url, s.include_bse_only)
            case "screener", "fundamentals":
                impl = ScreenerProvider(self.http, s.screener_cache_hours)
            case "exchange_bhavcopy", "market_data":
                impl = ExchangePricesProvider(self.session_factory)
            case "nse", "announcements":
                impl = NseAnnouncementsProvider(self.http)
            case _:
                raise ValueError(f"unknown {capability} provider {name!r}")
        self.cache[key] = impl
        return impl


def build_providers(
    settings: Settings,
    http: PoliteHttpClient | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> Providers:
    f = _Factory(settings, http, session_factory)
    return Providers(
        universe=f.build(settings.universe_provider, "universe"),
        fundamentals=f.build(settings.fundamentals_provider, "fundamentals"),
        market_data=f.build(settings.market_data_provider, "market_data"),
        announcements=f.build(settings.announcements_provider, "announcements"),
    )


@lru_cache
def get_providers() -> Providers:
    return build_providers(get_settings())
