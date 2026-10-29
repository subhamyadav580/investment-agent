from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonType, utcnow


class ScreeningRun(Base):
    __tablename__ = "screening_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    as_of_date: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(16), default="universe")  # universe | events
    universe_version: Mapped[str] = mapped_column(String(64))
    rules_version: Mapped[str] = mapped_column(String(32))
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    universe_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | completed | failed
    summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class ScreeningResult(Base):
    __tablename__ = "screening_results"
    __table_args__ = (UniqueConstraint("run_id", "company_id", name="uq_screening_result"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("screening_runs.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    # candidate | rejected | ineligible | governance_review | excluded_instrument
    status: Mapped[str] = mapped_column(String(32))
    score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    dimension_scores: Mapped[dict] = mapped_column(JsonType, default=dict)
    passed_rules: Mapped[list] = mapped_column(JsonType, default=list)
    failed_rules: Mapped[list] = mapped_column(JsonType, default=list)
    exclusion_reasons: Mapped[list] = mapped_column(JsonType, default=list)
    data_quality: Mapped[dict] = mapped_column(JsonType, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)


class ResearchQueueItem(Base):
    __tablename__ = "research_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("screening_runs.id", ondelete="SET NULL"))
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    report_id: Mapped[int | None] = mapped_column(Integer)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
