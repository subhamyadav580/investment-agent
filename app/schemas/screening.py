from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Metric(BaseModel):
    """One deterministic metric with the inputs that produced it (for auditability)."""

    key: str
    value: float | None
    unit: str  # ratio | pct | x | days | INR_crore | count
    period: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class RuleResult(BaseModel):
    rule_id: str
    stage: str  # eligibility | quality | valuation | governance | liquidity
    status: str  # pass | fail | missing | not_applicable | flag
    hard: bool = False
    observed: float | str | None = None
    threshold: float | str | None = None
    message: str


class GovernanceFlag(BaseModel):
    code: str
    severity: str  # serious | warning
    message: str
    evidence_key: str | None = None


class CandidateEvaluation(BaseModel):
    symbol: str
    status: str  # candidate | rejected | ineligible | governance_review | excluded_instrument
    score: float | None = None
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    missing_components: list[str] = Field(default_factory=list)
    rule_results: list[RuleResult] = Field(default_factory=list)
    governance_flags: list[GovernanceFlag] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    # horizons: score = long_term (5-10y); medium_term (1-3y) has its own categories
    horizon_scores: dict[str, float] = Field(default_factory=dict)
    medium_term_scores: dict[str, float] = Field(default_factory=dict)
    medium_term_missing: list[str] = Field(default_factory=list)
    earnings_basis: str | None = None  # quarterly | annual
    catalysts: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def passed(self) -> list[RuleResult]:
        return [r for r in self.rule_results if r.status == "pass"]

    @property
    def failed(self) -> list[RuleResult]:
        return [r for r in self.rule_results if r.status in ("fail", "missing", "flag")]


# ---- API DTOs ----


class ScreeningRunRequest(BaseModel):
    as_of_date: date | None = None
    enqueue_top_n: int | None = Field(default=None, ge=0, le=200)
    horizon: Literal["long_term", "medium_term"] = "long_term"  # which score ranks candidates


class ScreeningRunOut(BaseModel):
    id: int
    run_at: datetime
    finished_at: datetime | None
    as_of_date: str
    universe_version: str
    rules_version: str
    universe_count: int
    candidate_count: int
    status: str
    summary: dict[str, Any]
    error: str | None = None


class ScreeningResultOut(BaseModel):
    symbol: str
    name: str
    sector: str | None
    status: str
    score: float | None
    rank: int | None
    dimension_scores: dict[str, Any]
    passed_rules: list[Any]
    failed_rules: list[Any]
    exclusion_reasons: list[Any]
    data_quality: dict[str, Any]


class ScreeningRunDetailOut(ScreeningRunOut):
    results: list[ScreeningResultOut]
