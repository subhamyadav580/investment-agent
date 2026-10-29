from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- Structured LLM outputs (validated by the SDK's parse helper, then by verify_evidence) ----


class Claim(BaseModel):
    statement: str = Field(description="One factual statement drawn from the provided context.")
    evidence_ids: list[str] = Field(description="Ids of the EVIDENCE items that support this statement.")
    metric_refs: list[str] = Field(description="Keys of METRICS this statement relies on, if any.")
    materiality: Literal["material", "minor"]


class BusinessAnalysis(BaseModel):
    business_overview: str
    competitive_position: str
    financial_trends: str
    claims: list[Claim]
    open_questions: list[str]


class ValuationCommentary(BaseModel):
    summary: str
    claims: list[Claim]


class RiskItem(BaseModel):
    category: Literal["financial", "governance", "regulatory", "business", "valuation", "data_quality"]
    description: str
    severity: Literal["low", "medium", "high"]
    evidence_ids: list[str]
    metric_refs: list[str]


class RiskAnalysis(BaseModel):
    risks: list[RiskItem]
    downside_scenarios: list[str]
    catalysts: list[str]
    monitor_next: list[str]
    invalidation_conditions: list[str]


# ---- Persisted report ----

Conclusion = Literal["worth_deeper_research", "watch", "insufficient_evidence"]


class EvidenceItem(BaseModel):
    id: str
    source_type: str
    provider: str
    title: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    is_synthetic: bool = False


class VerifiedClaim(BaseModel):
    section: str
    statement: str
    evidence_ids: list[str]
    metric_refs: list[str]
    materiality: str
    verified: bool
    problems: list[str] = Field(default_factory=list)


class ResearchReportDoc(BaseModel):
    """The structured report. Section numbering follows the plan's report format (7.3)."""

    # 1. identity
    symbol: str
    name: str
    exchange: str
    sector: str | None
    as_of_date: date
    # 2. summary
    research_status: Literal["complete", "partial", "insufficient_data"]
    executive_summary: str
    screening_score: float | None
    dimension_scores: dict[str, float]
    # 3-4
    business_overview: str | None
    competitive_position: str | None
    financial_performance: dict[str, Any]
    financial_commentary: str | None
    # 5-6
    valuation: dict[str, Any]
    valuation_commentary: str | None
    peer_comparison: dict[str, Any]
    # 7-8
    risks: list[dict[str, Any]]
    downside_scenarios: list[str]
    governance: dict[str, Any]
    # 9
    monitor_next: list[str]
    catalysts: list[str]
    # 10
    evidence: list[EvidenceItem]
    claims: list[VerifiedClaim]
    data_quality_limitations: list[str]
    # 11
    invalidation_conditions: list[str]
    # 12
    conclusion: Conclusion
    conclusion_rationale: list[str]
    open_questions: list[str]
    disclaimer: str = (
        "Research aid only. Not investment advice, not a buy/sell recommendation, and no guarantee of returns. "
        "Verify material facts against original filings before acting."
    )


# ---- API DTOs ----


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=120, description="Company name or NSE symbol")
    as_of_date: date | None = None


class ResearchReportOut(BaseModel):
    id: int
    symbol: str
    as_of_date: date
    status: str
    conclusion: str
    model_version: str | None
    prompt_version: str
    rules_version: str
    created_at: datetime
    report: dict[str, Any]


class ResearchReportSummaryOut(BaseModel):
    id: int
    symbol: str
    as_of_date: date
    status: str
    conclusion: str
    created_at: datetime


class QueueProcessOut(BaseModel):
    processed: int
    succeeded: int
    failed: int
    report_ids: list[int]
