from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class InvalidationCondition(BaseModel):
    metric: str = Field(description="Metric key, e.g. roce_latest, debt_to_equity, revenue_cagr")
    op: Literal["<", "<=", ">", ">="]
    value: float
    description: str | None = None


class ValuationRange(BaseModel):
    metric: Literal["pe", "pb", "ev_ebitda"] = "pe"
    low: float
    high: float
    assumptions: str = Field(min_length=1, description="Why this range - required, ranges need stated assumptions")


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class WatchlistCompanyIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    thesis: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[InvalidationCondition] = Field(default_factory=list)
    alert_overrides: dict[str, float] = Field(default_factory=dict)
    valuation_range: ValuationRange | None = None
    review_date: date | None = None


class WatchlistCompanyOut(BaseModel):
    symbol: str
    name: str
    thesis: str | None
    assumptions: list[Any]
    invalidation_conditions: list[Any]
    alert_overrides: dict[str, Any]
    valuation_range: dict[str, Any] | None
    review_date: date | None
    needs_review: bool
    last_checked_at: datetime | None
    added_at: datetime


class WatchlistOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    companies: list[WatchlistCompanyOut] = Field(default_factory=list)
