from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonType, utcnow


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_companies_symbol_exchange"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(8), default="NSE")
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    bse_code: Mapped[str | None] = mapped_column(String(12), index=True)  # BSE scrip code, when known
    name: Mapped[str] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    sector_group: Mapped[str | None] = mapped_column(String(32))  # financial | non_financial
    instrument_type: Mapped[str] = mapped_column(String(32), default="EQUITY")
    series: Mapped[str | None] = mapped_column(String(8))
    is_sme: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    listed_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CompanyAlias(Base):
    """Symbol/name history so renamed or re-listed companies still resolve."""

    __tablename__ = "company_aliases"
    __table_args__ = (UniqueConstraint("company_id", "alias", "alias_type", name="uq_company_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(255), index=True)
    alias_type: Mapped[str] = mapped_column(String(16))  # symbol | name
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class Source(Base):
    """Provenance for any piece of retrieved data (filing, price file, announcement)."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("provider", "content_hash", name="uq_sources_provider_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(1024))
    title: Mapped[str | None] = mapped_column(String(512))
    document_id: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict] = mapped_column(JsonType, default=dict)


class FinancialSnapshot(Base):
    __tablename__ = "financial_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "period", "period_type", "metric", "consolidation_type", "source_id",
            name="uq_financial_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(16))  # FY2026, Q2FY2027, TTM-2026-09
    period_end: Mapped[date] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(8))  # FY | Q | TTM
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    consolidation_type: Mapped[str] = mapped_column(String(16))  # consolidated | standalone
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyPrice(Base):
    """Whole-market daily closes from exchange price files (bhavcopy). Keyed by the exchange's own identifier:
    NSE symbol for NSE, scrip code for BSE."""

    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("exchange", "security_key", "trade_date", name="uq_daily_price"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(8))
    security_key: Mapped[str] = mapped_column(String(32), index=True)
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    series: Mapped[str | None] = mapped_column(String(8))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    traded_value: Mapped[float | None] = mapped_column(Float)  # INR


class PriceFile(Base):
    """Which exchange price files have been processed (or confirmed absent, e.g. holidays)."""

    __tablename__ = "price_files"
    __table_args__ = (UniqueConstraint("exchange", "trade_date", name="uq_price_file"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(8))
    trade_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))  # loaded | missing
    rows: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("company_id", "timestamp", "source_id", name="uq_market_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
