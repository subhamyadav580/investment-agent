"""Reads company data you have collected yourself (from annual reports, exchange filings, or exports you are
licensed to use) in the normalized layout documented in data/local/README.md:

    <dir>/fundamentals/<SYMBOL>.json     company document (sector, annual figures, shareholding, source)
    <dir>/prices/<SYMBOL>.csv            date,close,volume
    <dir>/announcements/<SYMBOL>.json    [ {category, title, published_at, url, event_date?, summary?} ]
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from app.schemas.market_data import (
    Announcement,
    CompanyProfile,
    FinancialStatements,
    PriceBar,
    PriceHistory,
    Shareholding,
    SourceRef,
)
from app.services.data.normalization import normalize_symbol, parse_announcement, parse_company_document
from app.services.data.providers.base import DataNotAvailable


class LocalFilesProvider:
    name = "local_files"

    def __init__(self, root: Path):
        self.root = root

    def _mtime(self, path: Path) -> datetime:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)

    def _fundamentals_path(self, symbol: str) -> Path:
        path = self.root / "fundamentals" / f"{normalize_symbol(symbol)}.json"
        if not path.exists():
            raise DataNotAvailable(f"{symbol}: no local fundamentals file")
        return path

    def _parsed(self, symbol: str):
        path = self._fundamentals_path(symbol)
        return parse_company_document(
            normalize_symbol(symbol), json.loads(path.read_text()), provider=self.name, retrieved_at=self._mtime(path)
        )

    def get_profile(self, symbol: str) -> CompanyProfile:
        return self._parsed(symbol)[0]

    def get_financials(self, symbol: str) -> FinancialStatements:
        return self._parsed(symbol)[1]

    def get_shareholding(self, symbol: str) -> list[Shareholding]:
        return self._parsed(symbol)[2]

    def get_price_history(self, symbol: str, start: date, end: date) -> PriceHistory:
        sym = normalize_symbol(symbol)
        path = self.root / "prices" / f"{sym}.csv"
        if not path.exists():
            raise DataNotAvailable(f"{sym}: no local price file")
        df = pd.read_csv(path, parse_dates=["date"])
        df = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)].sort_values("date")
        bars = [
            PriceBar(date=r.date.date(), close=float(r.close), volume=float(r.volume) if "volume" in df else None)
            for r in df.itertuples()
        ]
        source = SourceRef(
            key=f"{sym}:prices",
            provider=self.name,
            source_type="price_feed",
            title=path.name,
            retrieved_at=self._mtime(path),
        )
        return PriceHistory(symbol=sym, bars=bars, source=source)

    def get_announcements(self, symbol: str, since: date) -> list[Announcement]:
        sym = normalize_symbol(symbol)
        path = self.root / "announcements" / f"{sym}.json"
        if not path.exists():
            return []
        retrieved = self._mtime(path)
        items = [parse_announcement(sym, a, self.name, retrieved, False) for a in json.loads(path.read_text())]
        return [a for a in items if a.published_at.date() >= since]
