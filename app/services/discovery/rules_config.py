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
    # Conservative / base / optimistic scenarios (explicit assumptions, never a price target)
    scenario_years: int = 5
    scenario_growth_spread: float = 0.05  # conservative = base - spread, optimistic = base + spread
    scenario_min_growth: float = -0.10
    scenario_max_growth: float = 0.25
    scenario_margin_headroom: float = 0.05  # base profit growth capped at revenue growth + this
    sector_multiple_band: float = 0.20  # without own history: sector median x (1 -/+ band)
    attractive_base_return: float = 0.12  # implied annual price change, base case
    expensive_base_return: float = 0.05


class GovernanceCfg(BaseModel):
    serious_flags: list[str]
    warning_flags: list[str] = []
    pledge_warning_pct: float
    pledge_serious_pct: float
    promoter_drop_warning_pp: float
    lookback_days: int = 365


class ScoringCfg(BaseModel):
    weights: dict[str, float]
    weights_financial: dict[str, float] | None = None  # banks, NBFCs, insurers; defaults to `weights`

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        for name, w in (("weights", self.weights), ("weights_financial", self.weights_financial)):
            if w is None:
                continue
            if abs(sum(w.values()) - 1.0) > 1e-6:
                raise ValueError(f"scoring.{name} must sum to 1.0, got {sum(w.values())}")
            if set(w) != set(self.weights):
                raise ValueError(f"scoring.{name} must weight the same categories as scoring.weights")
        return self

    def weights_for(self, sector_group: str) -> dict[str, float]:
        return self.weights_financial if sector_group == "financial" and self.weights_financial else self.weights


class ResearchCfg(BaseModel):
    enqueue_top_n: int = 30
    min_score_for_research: float = 50.0


class HorizonCfg(BaseModel):
    min_years: int
    max_years: int
    default_years: int


class MediumTermCfg(HorizonCfg):
    weights: dict[str, float]
    catalyst_lookback_days: int = 180
    catalyst_categories: list[str] = ["order_win", "capacity_expansion", "acquisition", "credit_rating_upgrade"]
    catalyst_points: float = 40.0  # per distinct kind of evidenced catalyst
    industry_tailwind_points: float = 30.0  # the company's industry has improving earnings

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        if abs(sum(self.weights.values()) - 1.0) > 1e-6:
            raise ValueError(f"horizons.medium_term.weights must sum to 1.0, got {sum(self.weights.values())}")
        return self


class HorizonsCfg(BaseModel):
    """Long-term (5-10 years) uses `scoring.weights`; medium-term (1-3 years) has its own categories and weights."""

    long_term: HorizonCfg = HorizonCfg(min_years=5, max_years=10, default_years=5)
    medium_term: MediumTermCfg = MediumTermCfg(
        min_years=1, max_years=3, default_years=2,
        weights={"business_financial_quality": 0.20, "earnings_outlook": 0.20, "financial_strength": 0.10,
                 "valuation": 0.20, "catalysts": 0.15, "management_risk": 0.15},
    )  # fmt: skip


class AssessmentCfg(BaseModel):
    """Thresholds that turn category scores into the report's final assessment and classification."""

    strong_score: float = 70.0  # category score at or above -> Strong / Positive
    weak_score: float = 45.0  # below -> Weak / Concerning
    strong_candidate_min_score: float = 65.0  # overall score needed for "strong candidate"
    data_quality_high: float = 80.0
    data_quality_medium: float = 60.0
    max_missing_components: int = 4  # more unscored components than this -> insufficient evidence
    # Red flags: reported separately and they make the classification "high risk" whatever the score
    red_flag_max_debt_to_equity: float = 2.0
    red_flag_min_cfo_to_pat: float = 0.3
    red_flag_max_gross_npa_pct: float = 10.0
    shortlist_classes: list[str] = ["strong_candidate", "good_business_expensive", "potential_opportunity"]
    auto_watchlist: str | None = "Auto shortlist"  # queued research adds strong candidates here; None disables
    auto_watchlist_classes: list[str] = ["strong_candidate", "good_business_expensive"]


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
    assessment: AssessmentCfg = Field(default_factory=AssessmentCfg)
    horizons: HorizonsCfg = Field(default_factory=HorizonsCfg)
    alerts: AlertsCfg = Field(default_factory=AlertsCfg)
    discovery: DiscoveryCfg = Field(default_factory=DiscoveryCfg)


@lru_cache
def load_screening_config(path: Path) -> ScreeningConfig:
    with path.open("rb") as f:
        return ScreeningConfig.model_validate(tomllib.load(f))
