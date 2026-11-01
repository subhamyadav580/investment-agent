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
    business_overview: str = Field(description="What the company does.")
    revenue_model: str = Field(description="How it makes money: segments, customers, pricing, as far as the context shows.")
    competitive_advantages: list[str] = Field(description="Advantages the evidence supports; empty if none are visible.")
    competitive_position: str
    financial_trends: str
    industry_outlook: str = Field(description="Industry direction as shown by the INDUSTRY TREND block and filings.")
    growth_drivers: list[str] = Field(description="Expansion plans and drivers visible in filings or metrics.")
    competitive_threats: list[str]
    claims: list[Claim]
    open_questions: list[str]


class ValuationCommentary(BaseModel):
    summary: str
    scenario_commentary: str = Field(description="What the conservative/base/optimistic assumptions mean in practice.")
    medium_term_view: str = Field(description="1-3 year view: earnings momentum, evidenced catalysts and their timing, "
                                  "and whether they already look priced in.")
    claims: list[Claim]


class RiskItem(BaseModel):
    category: Literal["financial", "governance", "regulatory", "business", "competition", "valuation", "data_quality"]
    description: str
    severity: Literal["low", "medium", "high"]
    evidence_ids: list[str]
    metric_refs: list[str]


class RiskAnalysis(BaseModel):
    management_assessment: str = Field(description="Promoter holding and pledging, governance events, capital allocation.")
    risks: list[RiskItem]
    downside_scenarios: list[str]
    catalysts: list[str]
    monitor_next: list[str]
    invalidation_conditions: list[str]


# ---- Persisted report ----

Classification = Literal[
    "strong_candidate", "good_business_expensive", "potential_opportunity", "high_risk", "insufficient_evidence"
]


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
    """The structured report. Sections 1-7 follow the report format in the README; each final-assessment rating
    carries its reasons, metric keys and evidence ids."""

    symbol: str
    name: str
    exchange: str
    sector: str | None
    industry: str | None = None
    as_of_date: date
    research_status: Literal["complete", "partial", "insufficient_data"]
    executive_summary: str
    screening_score: float | None
    dimension_scores: dict[str, float]
    score_weights: dict[str, float]
    horizon: dict[str, Any]  # requested, primary, years per horizon
    # 1. Company overview
    company_overview: dict[str, Any]
    # 2. Financial performance (5-10 years where available, peers)
    financial_performance: dict[str, Any]
    peer_comparison: dict[str, Any]
    # 3. Valuation (current, history, peers, scenarios)
    valuation: dict[str, Any]
    # 4. Management and governance
    management_governance: dict[str, Any]
    # 5. Growth prospects
    growth_prospects: dict[str, Any]
    # 6. Risks (red flags listed separately; invalidation conditions = when the thesis no longer holds)
    risks: dict[str, Any]
    # 7. Final assessment
    final_assessment: dict[str, Any]
    conclusion: Classification
    conclusion_label: str
    conclusion_rationale: list[str]
    # Monitoring and evidence trail
    monitor_next: list[str]
    catalysts: list[str]
    open_questions: list[str]
    evidence: list[EvidenceItem]
    claims: list[VerifiedClaim]
    data_quality_limitations: list[str]
    disclaimer: str = (
        "Research assessment only: not investment advice, not a buy/sell recommendation, and no guarantee of "
        "future returns. You make the final decision; verify material facts against the original filings first."
    )


class ShortlistItemOut(BaseModel):
    rank: int
    report_id: int
    symbol: str
    name: str
    sector: str | None
    as_of_date: date
    conclusion: str
    conclusion_label: str
    score: float | None
    ratings: dict[str, str]
    red_flags: int
    main_concern: str | None
    long_term: str | None  # classification label per horizon
    medium_term: str | None
    why: list[str]
    created_at: datetime


# ---- API DTOs ----


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=160,
                       description="Company name or NSE symbol, optionally with a horizon: 'Asian Paints for 5 years'")
    as_of_date: date | None = None
    horizon: Literal["long_term", "medium_term", "both"] | None = None  # overrides a horizon in the query text
    years: int | None = Field(default=None, ge=1, le=10)


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
    newly_monitored: list[str] = Field(default_factory=list)  # symbols auto-added to the shortlist watchlist
