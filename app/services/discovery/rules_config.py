"""Typed, versioned screening configuration loaded from config/screening_rules.*.toml."""

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class UniverseCfg(BaseModel):
    include_series: list[str]
    include_bse_groups: list[str] = ["A", "B", "T", "X", "XT", "P"]
    exclude_sme: bool = True
    allowed_instruments: list[str] = ["EQUITY"]


class EligibilityCfg(BaseModel):
    min_years: int = 3
    preferred_years: int = 5
    max_financials_age_days: int = 456
    max_price_age_days: int = 10
    conflict_tolerance: float = 0.02


class QualityCfg(BaseModel):
    min_revenue_cagr: float
    min_profit_positive_ratio: float
    min_roce: float
    min_roe_financial: float
    max_debt_to_equity: float
    min_interest_coverage: float
    critical_interest_coverage: float
    min_cfo_to_pat: float
    max_gross_npa_pct: float


class LiquidityCfg(BaseModel):
    min_avg_traded_value_cr: float


class ValuationCfg(BaseModel):
    max_pe_vs_sector_median: float
    max_pe_absolute: float
    max_pb_financial: float


class GovernanceCfg(BaseModel):
    serious_flags: list[str]
    warning_flags: list[str] = []
    pledge_warning_pct: float
    pledge_serious_pct: float
    promoter_drop_warning_pp: float
    lookback_days: int = 365


class ScoringCfg(BaseModel):
    weights: dict[str, float]

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"scoring weights must sum to 1.0, got {total}")
        return self


class ResearchCfg(BaseModel):
    enqueue_top_n: int = 30
    min_score_for_research: float = 50.0
    worth_deeper_research_score: float = 65.0


class AlertsCfg(BaseModel):
    margin_drop_pp: float = 0.03
    profit_decline: float = 0.20
    min_cfo_to_pat: float = 0.6
    max_debt_to_equity: float = 1.0
    min_interest_coverage: float = 2.5
    results_reminder_days: int = 7
    governance_categories: list[str] = ["auditor_resignation", "auditor_qualification", "sebi_order"]
    quiet_period_exempt: list[str] = ["governance_event", "thesis_review"]

    def with_overrides(self, overrides: dict[str, float] | None) -> "AlertsCfg":
        known = {k: v for k, v in (overrides or {}).items() if k in type(self).model_fields}
        return self.model_copy(update=known)


class DiscoveryCfg(BaseModel):
    event_categories: list[str] = ["results", "order_win", "acquisition", "capacity_expansion"]
    event_lookback_days: int = 2
    min_industry_companies: int = 3
    sector_tailwind_boost: float = 5.0
    liquidity_prefilter: bool = True


class ScreeningConfig(BaseModel):
    version: str
    universe: UniverseCfg
    eligibility: EligibilityCfg = Field(default_factory=EligibilityCfg)
    quality: QualityCfg
    liquidity: LiquidityCfg
    valuation: ValuationCfg
    governance: GovernanceCfg
    scoring: ScoringCfg
    research: ResearchCfg = Field(default_factory=ResearchCfg)
    alerts: AlertsCfg = Field(default_factory=AlertsCfg)
    discovery: DiscoveryCfg = Field(default_factory=DiscoveryCfg)


@lru_cache
def load_screening_config(path: Path) -> ScreeningConfig:
    with path.open("rb") as f:
        return ScreeningConfig.model_validate(tomllib.load(f))
