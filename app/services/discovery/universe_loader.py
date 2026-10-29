"""Builds the eligible equity universe: load, normalize identifiers, classify exclusions, persist."""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Company
from app.repos.company_repo import CompanyRepo
from app.schemas.market_data import UniverseEntry
from app.services.data.providers.base import UniverseProvider
from app.services.discovery.rules_config import UniverseCfg

logger = logging.getLogger(__name__)


@dataclass
class UniverseMember:
    entry: UniverseEntry
    company: Company
    exclusion: str | None  # None = in scope for screening


@dataclass
class UniverseLoad:
    version: str
    members: list[UniverseMember]

    @property
    def in_scope(self) -> list[UniverseMember]:
        return [m for m in self.members if m.exclusion is None]


def exclusion_reason(entry: UniverseEntry, cfg: UniverseCfg) -> str | None:
    if entry.instrument_type not in cfg.allowed_instruments:
        return f"instrument type {entry.instrument_type} is not a listed operating company"
    if entry.is_sme and cfg.exclude_sme:
        return "SME platform listing (excluded by default)"
    if entry.exchange == "BSE":
        if entry.series and entry.series not in cfg.include_bse_groups:
            return f"BSE group {entry.series} is not an included main-board group"
    elif entry.series and entry.series not in cfg.include_series:
        return f"series {entry.series} is not a main-board equity series"
    return None


def load_universe(session: Session, provider: UniverseProvider, cfg: UniverseCfg) -> UniverseLoad:
    entries, version = provider.load_universe()
    repo = CompanyRepo(session)
    members: list[UniverseMember] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry.symbol, entry.exchange)
        if key in seen:  # duplicate rows in source files happen; first wins
            continue
        seen.add(key)
        company = repo.upsert_from_universe(entry)
        repo.add_alias(company.id, entry.symbol, "symbol")
        members.append(UniverseMember(entry=entry, company=company, exclusion=exclusion_reason(entry, cfg)))

    exchanges = {m.company.exchange for m in members}
    for exchange in exchanges:
        ids = {m.company.id for m in members if m.company.exchange == exchange}
        if n := repo.mark_inactive_except(exchange, ids):
            logger.info("marked delisted/missing companies inactive", extra={"exchange": exchange, "count": n})
    logger.info(
        "universe loaded",
        extra={"version": version, "total": len(members), "in_scope": sum(m.exclusion is None for m in members)},
    )
    return UniverseLoad(version=version, members=members)
