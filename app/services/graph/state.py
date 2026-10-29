"""LangGraph state. Plain dict fields mirror the plan's schema (6.3); typed objects carry the
deterministic pipeline outputs between nodes (no checkpointer, so they need not be serializable)."""

import operator
from typing import Annotated, Any, TypedDict

from app.schemas.market_data import CompanyData, DataQualityReport
from app.schemas.research import BusinessAnalysis, RiskAnalysis, ValuationCommentary
from app.services.discovery.company_evaluator import EvaluatedCompany


class ResearchState(TypedDict, total=False):
    query: str
    as_of_date: str
    company_id: int
    symbol: str
    company_name: str
    exchange: str
    sector: str | None
    sector_group: str

    data: CompanyData
    fetch_attempts: int
    source_ids: dict[str, int]  # SourceRef.key -> sources.id

    data_quality: DataQualityReport
    evaluated: EvaluatedCompany
    metrics: dict[str, Any]  # key -> Metric.model_dump()
    valuation: dict[str, Any]
    peer_comparison: dict[str, Any]
    evidence: list[dict[str, Any]]  # EvidenceItem dicts, ids E1..En
    evidence_key_by_id: dict[str, str]

    business: BusinessAnalysis | None
    valuation_commentary: ValuationCommentary | None
    risk_analysis: RiskAnalysis | None
    verified_claims: list[dict[str, Any]]

    report: dict[str, Any]
    report_id: int
    alerts: list[dict[str, Any]]

    llm_calls: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
