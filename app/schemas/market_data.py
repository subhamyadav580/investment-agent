"""Normalized, provider-agnostic data contracts. Every provider adapter must emit these shapes.

Monetary values are always INR crore after normalization (see services/data/normalization.py).
"""

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PeriodType(StrEnum):
    FY = "FY"
    QUARTER = "Q"
    TTM = "TTM"


class Consolidation(StrEnum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class SourceRef(BaseModel):
    """Where a piece of data came from. `key` is stable within one fetch and used for evidence ids."""

    key: str
    provider: str
    source_type: str  # annual_report | quarterly_result | exchange_filing | price_feed | announcement | fixture
    url: str | None = None
    title: str | None = None
    document_id: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    is_synthetic: bool = False

    def content_hash(self, payload: object) -> str:
        blob = json.dumps({"key": self.key, "url": self.url, "payload": payload}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


class FinancialValue(BaseModel):
    period: str  # FY2026
    period_end: date
    period_type: PeriodType = PeriodType.FY
    metric: str
    value: float | None
    unit: str = "INR_crore"
    consolidation: Consolidation = Consolidation.CONSOLIDATED
    source_key: str


class FinancialStatements(BaseModel):
    symbol: str
    values: list[FinancialValue] = Field(default_factory=list)
    shares_outstanding_cr: float | None = None  # shares, in crore
    sources: dict[str, SourceRef] = Field(default_factory=dict)

    def periods(self, period_type: PeriodType = PeriodType.FY) -> list[str]:
        ends = {v.period: v.period_end for v in self.values if v.period_type == period_type}
        return sorted(ends, key=lambda p: ends[p])

    def period_end(self, period: str) -> date | None:
        return next((v.period_end for v in self.values if v.period == period), None)

    def series(self, metric: str, period_type: PeriodType = PeriodType.FY) -> dict[str, float | None]:
        """period -> value, oldest first. If multiple sources disagree the first one wins
        (conflicts are surfaced separately by data validation)."""
        out: dict[str, float | None] = {}
        for period in self.periods(period_type):
            for v in self.values:
                if v.period == period and v.metric == metric and v.period_type == period_type:
                    out[period] = v.value
                    break
        return out


class PriceBar(BaseModel):
    date: date
    close: float
    volume: float | None = None


class PriceHistory(BaseModel):
    symbol: str
    bars: list[PriceBar] = Field(default_factory=list)
    source: SourceRef | None = None

    @property
    def last(self) -> PriceBar | None:
        return self.bars[-1] if self.bars else None


class Announcement(BaseModel):
    id: str
    symbol: str
    # auditor_resignation | auditor_qualification | sebi_order | pledge_change | results | board_meeting | other
    category: str
    title: str
    published_at: datetime
    event_date: date | None = None  # e.g. scheduled results date
    summary: str | None = None
    source: SourceRef


class Shareholding(BaseModel):
    period_end: date
    promoter_holding_pct: float | None = None
    promoter_pledged_pct: float | None = None  # % of promoter holding that is pledged
    source: SourceRef


class CompanyProfile(BaseModel):
    symbol: str
    sector: str | None = None
    industry: str | None = None


class UniverseEntry(BaseModel):
    symbol: str
    name: str
    exchange: str = "NSE"
    isin: str | None = None
    bse_code: str | None = None
    series: str | None = None
    instrument_type: str = "EQUITY"  # EQUITY | ETF | REIT | INVIT | DEBT | OTHER
    is_sme: bool = False
    listed_on: date | None = None


class CompanyData(BaseModel):
    """Everything fetched for one company in one pass."""

    symbol: str
    profile: CompanyProfile | None = None
    financials: FinancialStatements | None = None
    prices: PriceHistory | None = None
    announcements: list[Announcement] = Field(default_factory=list)
    shareholding: list[Shareholding] = Field(default_factory=list)
    fetch_errors: list[str] = Field(default_factory=list)

    def all_sources(self) -> dict[str, SourceRef]:
        sources: dict[str, SourceRef] = {}
        if self.financials:
            sources.update(self.financials.sources)
        if self.prices and self.prices.source:
            sources[self.prices.source.key] = self.prices.source
        for a in self.announcements:
            sources[a.source.key] = a.source
        for s in self.shareholding:
            sources[s.source.key] = s.source
        return sources


class DataIssue(BaseModel):
    code: str
    severity: str  # error | warning | info
    message: str
    field: str | None = None


class DataQualityReport(BaseModel):
    is_eligible: bool
    score: float  # 0-100
    years_available: int
    latest_period: str | None = None
    latest_period_end: date | None = None
    consolidation: str | None = None
    issues: list[DataIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[DataIssue]:
        return [i for i in self.issues if i.severity == "error"]
