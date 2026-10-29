from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AlertCandidate(BaseModel):
    """Output of a deterministic alert rule, before dedup/persistence."""

    rule_id: str
    severity: str  # info | warning | critical
    symbol: str
    exchange: str
    trigger: str
    threshold: float | str | None
    observed: float | str | None
    comparison_period: str | None = None
    why_it_matters: str
    follow_up: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)
    fingerprint: str  # what makes two triggers "the same event" for dedup


class AlertOut(BaseModel):
    id: int
    symbol: str
    rule_id: str
    severity: str
    triggered_at: datetime
    delivery_status: str
    attempts: int
    payload: dict[str, Any]


class MonitoringRunOut(BaseModel):
    companies_checked: int
    alerts_created: int
    alerts_delivered: int
    errors: list[str]
