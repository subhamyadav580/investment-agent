"""Fetch everything we know about a company from the configured providers and persist provenance."""

import logging
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import TypeVar

from sqlalchemy.orm import Session

from app.models import Company
from app.repos.snapshot_repo import SnapshotRepo
from app.schemas.market_data import CompanyData, CompanyProfile
from app.services.data.providers.base import DataNotAvailable, ProviderError
from app.services.data.providers.registry import Providers
from app.services.discovery.sector_classifier import classify_sector_group

logger = logging.getLogger(__name__)

T = TypeVar("T")

PRICE_LOOKBACK_DAYS = 1200  # enough for 1y return + historical P/E at the last few FY ends
ANNOUNCEMENT_LOOKBACK_DAYS = 400
RETRIES = 2


def _call[T](label: str, fn: Callable[[], T], errors: list[str]) -> T | None:
    for attempt in range(RETRIES + 1):
        try:
            return fn()
        except DataNotAvailable:
            return None
        except ProviderError as e:
            if attempt == RETRIES:
                errors.append(f"{label}: {e}")
                logger.warning("provider call failed", extra={"call": label, "error": str(e)})
                return None
            time.sleep(0.5 * 2**attempt)
    return None


def fetch_company_data(providers: Providers, symbol: str, as_of: date) -> CompanyData:
    errors: list[str] = []
    f, m, a = providers.fundamentals, providers.market_data, providers.announcements
    data = CompanyData(
        symbol=symbol,
        profile=_call("profile", lambda: f.get_profile(symbol), errors),
        financials=_call("financials", lambda: f.get_financials(symbol), errors),
        prices=_call(
            "prices", lambda: m.get_price_history(symbol, as_of - timedelta(days=PRICE_LOOKBACK_DAYS), as_of), errors
        ),
        announcements=_call(
            "announcements",
            lambda: a.get_announcements(symbol, as_of - timedelta(days=ANNOUNCEMENT_LOOKBACK_DAYS)),
            errors,
        )
        or [],
        shareholding=_call("shareholding", lambda: f.get_shareholding(symbol), errors) or [],
        fetch_errors=errors,
    )
    # Pledge disclosures come from the exchange; append so the latest-dated record carries the pledge figure.
    if hasattr(a, "get_pledge") and (pledge := _call("pledge", lambda: a.get_pledge(symbol), errors)):
        data.shareholding = sorted([*data.shareholding, pledge], key=lambda s: s.period_end)
    # Point-in-time discipline: drop anything dated after as_of.
    if data.prices:
        data.prices.bars = [b for b in data.prices.bars if b.date <= as_of]
    data.announcements = [x for x in data.announcements if x.published_at.date() <= as_of]
    data.shareholding = [x for x in data.shareholding if x.period_end <= as_of]
    if data.financials:
        data.financials.values = [v for v in data.financials.values if v.period_end <= as_of]
    return data


def apply_profile(company: Company, profile: CompanyProfile | None) -> str:
    """Update sector fields from the provider profile; returns the sector group."""
    if profile:
        company.sector = profile.sector or company.sector
        company.industry = profile.industry or company.industry
    group, _ = classify_sector_group(company.sector, company.industry, company.name)
    company.sector_group = group
    return group


def persist_company_data(session: Session, company: Company, data: CompanyData) -> dict[str, int]:
    """Store sources + snapshots. Returns source_key -> sources.id."""
    repo = SnapshotRepo(session)
    source_ids: dict[str, int] = {}
    if data.financials:
        for key, ref in data.financials.sources.items():
            payload = [v.model_dump(mode="json") for v in data.financials.values if v.source_key == key]
            source_ids[key] = repo.get_or_create_source(company.id, ref, ref.content_hash(payload)).id
        repo.add_financials(company.id, data.financials.values, source_ids)
    if data.prices and data.prices.source and data.prices.bars:
        ref = data.prices.source
        bars = data.prices.bars
        src = repo.get_or_create_source(company.id, ref, ref.content_hash([bars[0].date, bars[-1].date, len(bars)]))
        source_ids[ref.key] = src.id
        repo.add_market_bars(company.id, bars, src.id)
    for ann in data.announcements:
        source_ids[ann.source.key] = repo.get_or_create_source(
            company.id, ann.source, ann.source.content_hash(ann.model_dump(mode="json", exclude={"source"}))
        ).id
    for sh in data.shareholding:
        source_ids[sh.source.key] = repo.get_or_create_source(
            company.id, sh.source, sh.source.content_hash(sh.model_dump(mode="json", exclude={"source"}))
        ).id
    return source_ids
