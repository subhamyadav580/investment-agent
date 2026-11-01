from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonType, utcnow


class ResearchReport(Base):
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))  # complete | partial | insufficient_data
    conclusion: Mapped[str] = mapped_column(String(32))  # a Classification (schemas/research.py)
    report_json: Mapped[dict] = mapped_column(JsonType)
    metrics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    model_version: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    rules_version: Mapped[str] = mapped_column(String(32))
    source_snapshot: Mapped[list] = mapped_column(JsonType, default=list)  # [{source_id, content_hash}]
    llm_usage: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchlistCompany(Base):
    __tablename__ = "watchlist_companies"
    __table_args__ = (UniqueConstraint("watchlist_id", "company_id", name="uq_watchlist_company"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    thesis: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[list] = mapped_column(JsonType, default=list)
    # [{"metric": "roce_latest", "op": "<", "value": 0.15, "description": "..."}]
    invalidation_conditions: Mapped[list] = mapped_column(JsonType, default=list)
    # per-company alert threshold overrides, e.g. {"max_debt_to_equity": 0.8}
    alert_overrides: Mapped[dict] = mapped_column(JsonType, default=dict)
    # {"metric": "pe", "low": 18, "high": 25, "assumptions": "..."}
    valuation_range: Mapped[dict | None] = mapped_column(JsonType)
    review_date: Mapped[date | None] = mapped_column(Date)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    last_metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
