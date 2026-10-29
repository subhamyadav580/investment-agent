"""Synthetic sample data for development, demos, and tests.

Every company in the fixture is FICTIONAL and every source is marked `is_synthetic=True`, so reports built
from it can never be mistaken for research on a real listed company.
"""

import hashlib
import json
import math
import random
from datetime import UTC, date, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any

from app.schemas.market_data import (
    Announcement,
    CompanyProfile,
    FinancialStatements,
    PriceBar,
    PriceHistory,
    Shareholding,
    SourceRef,
    UniverseEntry,
)
from app.services.data.normalization import normalize_symbol, parse_company_document
from app.services.data.providers.base import DataNotAvailable

PROVIDER_NAME = "fixture"


class FixtureProvider:
    name = PROVIDER_NAME

    def __init__(self, path: Path):
        self.path = path

    @cached_property
    def _doc(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    @cached_property
    def _retrieved_at(self) -> datetime:
        return datetime.fromisoformat(self._doc["as_of"]).replace(tzinfo=UTC)

    def _company(self, symbol: str) -> dict[str, Any]:
        doc = self._doc["companies"].get(normalize_symbol(symbol))
        if doc is None:
            raise DataNotAvailable(f"{symbol}: not in fixture")
        return doc

    def _parsed(self, symbol: str):
        return parse_company_document(
            normalize_symbol(symbol),
            self._company(symbol),
            provider=self.name,
            retrieved_at=self._retrieved_at,
            is_synthetic=True,
        )

    # --- UniverseProvider ---
    def load_universe(self) -> tuple[list[UniverseEntry], str]:
        entries = [UniverseEntry(**e) for e in self._doc["universe"]]
        version = "fixture-" + hashlib.sha256(self.path.read_bytes()).hexdigest()[:12]
        return entries, version

    # --- FundamentalsProvider ---
    def get_profile(self, symbol: str) -> CompanyProfile:
        return self._parsed(symbol)[0]

    def get_financials(self, symbol: str) -> FinancialStatements:
        fin = self._parsed(symbol)[1]
        if not fin.values:
            raise DataNotAvailable(f"{symbol}: no financials in fixture")
        return fin

    def get_shareholding(self, symbol: str) -> list[Shareholding]:
        return self._parsed(symbol)[2]

    # --- AnnouncementsProvider ---
    def get_announcements(self, symbol: str, since: date) -> list[Announcement]:
        return [a for a in self._parsed(symbol)[3] if a.published_at.date() >= since]

    def market_announcements(self, start: date, end: date) -> list[Announcement]:
        out = []
        for sym in self._doc["companies"]:
            out += [a for a in self._parsed(sym)[3] if start <= a.published_at.date() <= end]
        return out

    # --- MarketDataProvider ---
    def get_price_history(self, symbol: str, start: date, end: date) -> PriceHistory:
        sym = normalize_symbol(symbol)
        model = self._company(sym).get("price_model")
        if not model:
            raise DataNotAvailable(f"{sym}: no price data in fixture")
        bars = [b for b in _generate_prices(sym, model) if start <= b.date <= end]
        source = SourceRef(
            key=f"{sym}:prices",
            provider=self.name,
            source_type="price_feed",
            title=f"{sym} synthetic daily closes",
            retrieved_at=self._retrieved_at,
            is_synthetic=True,
        )
        return PriceHistory(symbol=sym, bars=bars, source=source)


def _generate_prices(symbol: str, model: dict[str, Any]) -> list[PriceBar]:
    """Deterministic random walk that ENDS at `end_price` on `last_date` (so valuation tests are stable)."""
    rng = random.Random(symbol)
    last = date.fromisoformat(model["last_date"])
    days: list[date] = []
    d = last
    while len(days) < model.get("days", 800):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()

    drift = model.get("annual_drift", 0.10) / 252
    vol = model.get("daily_vol", 0.015)
    log_returns = [rng.gauss(drift, vol) for _ in days[1:]]
    total = sum(log_returns)
    price = model["end_price"] / math.exp(total)
    bars = [PriceBar(date=days[0], close=round(price, 2), volume=_volume(rng, model))]
    for day, r in zip(days[1:], log_returns, strict=True):
        price *= math.exp(r)
        bars.append(PriceBar(date=day, close=round(price, 2), volume=_volume(rng, model)))
    return bars


def _volume(rng: random.Random, model: dict[str, Any]) -> float:
    return float(max(1, int(model.get("avg_volume", 100_000) * rng.uniform(0.5, 1.5))))
