"""Validate -> metrics -> governance -> rules -> score for ONE company. Shared by the screening pipeline and
the LangGraph research workflow so both always apply identical, versioned rules."""

from dataclasses import dataclass
from datetime import date

from app.schemas.market_data import CompanyData, DataQualityReport
from app.schemas.screening import CandidateEvaluation, GovernanceFlag, Metric, RuleResult
from app.services.data.freshness import validate_company_data
from app.services.discovery.rules_config import ScreeningConfig
from app.services.discovery.scoring import evaluate_candidate
from app.services.discovery.screening_rules import derived_values, detect_governance_flags, evaluate_rules
from app.services.research.metrics import compute_metrics, metrics_to_values


@dataclass
class PreparedCompany:
    """Stage 1 output (no peer context needed)."""

    symbol: str
    sector: str | None
    sector_group: str
    data: CompanyData
    data_quality: DataQualityReport
    metrics: dict[str, Metric]

    @property
    def values(self) -> dict[str, float | None]:
        return metrics_to_values(self.metrics)


@dataclass
class EvaluatedCompany:
    prepared: PreparedCompany
    values: dict[str, float | None]  # metrics + peer-relative derived values
    flags: list[GovernanceFlag]
    rules: list[RuleResult]
    evaluation: CandidateEvaluation


def prepare(data: CompanyData, sector: str | None, sector_group: str, as_of: date, cfg: ScreeningConfig) -> PreparedCompany:
    dq = validate_company_data(data, sector_group, as_of, cfg.eligibility)
    metrics = compute_metrics(data, sector_group, as_of)
    return PreparedCompany(data.symbol, sector, sector_group, data, dq, metrics)


def evaluate(
    prepared: PreparedCompany, sector_medians: dict[str, float] | None, as_of: date, cfg: ScreeningConfig
) -> EvaluatedCompany:
    values = derived_values(prepared.values, sector_medians)
    flags = detect_governance_flags(prepared.data, as_of, cfg.governance)
    rules = evaluate_rules(values, prepared.data_quality, prepared.sector_group, flags, cfg)
    evaluation = evaluate_candidate(
        prepared.symbol, values, prepared.data_quality, prepared.sector_group, flags, rules, cfg
    )
    return EvaluatedCompany(prepared, values, flags, rules, evaluation)
