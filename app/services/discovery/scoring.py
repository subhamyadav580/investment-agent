"""Explainable 0-100 research-priority score over five categories. It prioritizes research; it does not predict
returns.

| Category                  | Default weight | Evidence used (non-financials / lenders)                                   |
|---------------------------|----------------|-----------------------------------------------------------------------------|
| business_quality          | 25%            | sustained ROCE, margin level and stability / ROE, ROA                       |
| financial_performance     | 25%            | revenue and profit growth, consistency, ROCE, cash conversion / ROE         |
| financial_strength        | 15%            | debt/equity, interest cover, net debt/EBITDA / capital adequacy, NPAs       |
| valuation                 | 20%            | P/E or P/B versus sector, absolute multiples                                |
| management_governance     | 15%            | governance events, pledging, promoter trend, return on incremental capital  |

Lenders use their own weights (`[scoring.weights_financial]`).

- Each category is the mean of linearly-scaled components.
- A missing component scores 0 and is reported in `missing_components` - it never gets a free pass.
- Serious governance flags do not get averaged away: they zero management_governance AND set
  status=governance_review, so they are reported separately from the score.
"""

from datetime import date, timedelta

from app.schemas.market_data import Announcement, DataQualityReport
from app.schemas.screening import CandidateEvaluation, GovernanceFlag, RuleResult
from app.services.discovery.rules_config import MediumTermCfg, ScreeningConfig
from app.services.discovery.sector_classifier import FINANCIAL

# (metric, worst, best): linear from 0 at `worst` to 100 at `best` (works for inverse metrics too)
Component = tuple[str, float, float]

COMPONENTS: dict[str, dict[str, list[Component]]] = {
    "business_quality": {
        "non_financial": [("roce_avg_3y", 0.05, 0.30), ("operating_margin_avg", 0.03, 0.25),
                          ("operating_margin_stdev", 0.08, 0.01)],
        FINANCIAL: [("roe_avg_3y", 0.05, 0.20), ("roa_latest", 0.003, 0.02)],
    },
    "financial_performance": {
        "non_financial": [("revenue_cagr", 0.0, 0.20), ("profit_cagr", 0.0, 0.25), ("profit_positive_ratio", 0.4, 1.0),
                          ("roce_latest", 0.05, 0.30), ("cfo_to_pat_3y", 0.3, 1.0)],
        FINANCIAL: [("revenue_cagr", 0.0, 0.20), ("profit_cagr", 0.0, 0.25), ("profit_positive_ratio", 0.4, 1.0),
                    ("roe_latest", 0.05, 0.20)],
    },
    "financial_strength": {
        "non_financial": [("debt_to_equity", 2.0, 0.0), ("interest_coverage", 1.5, 10.0), ("net_debt_to_ebitda", 4.0, 0.0)],
        FINANCIAL: [("capital_adequacy_ratio", 11.0, 20.0), ("gross_npa_pct", 8.0, 1.0)],
    },
    "valuation": {
        "non_financial": [("pe_vs_sector", 2.0, 0.6), ("pe", 60.0, 10.0), ("ev_ebitda", 35.0, 8.0)],
        FINANCIAL: [("pb_vs_sector", 2.0, 0.6), ("pb", 5.0, 1.0)],
    },
    "management_governance": {
        # governance_events is added by dimension_scores (it is not a metric)
        "non_financial": [("promoter_pledged_pct", 50.0, 0.0), ("promoter_holding_change_1y", -5.0, 0.0),
                          ("return_on_incremental_capital", 0.0, 0.25)],
        FINANCIAL: [("promoter_pledged_pct", 50.0, 0.0), ("promoter_holding_change_1y", -5.0, 0.0),
                    ("return_on_incremental_capital", 0.0, 0.20)],
    },
}  # fmt: skip

GOVERNANCE_WARNING_PENALTY = 25.0
# Absent from the data for reasons that are not the company's fault: skipped and noted, never zeroed.
NOT_PENALIZED = {
    "promoter_holding_change_1y": "less than a year of shareholding history",
    "promoter_pledged_pct": "pledge data not reported; exchanges publish it mainly when shares are pledged",
}


def scale(value: float, worst: float, best: float) -> float:
    if best == worst:
        return 100.0
    return max(0.0, min(100.0, (value - worst) / (best - worst) * 100.0))


def governance_events_score(flags: list[GovernanceFlag]) -> float:
    if any(f.severity == "serious" for f in flags):
        return 0.0
    return max(0.0, 100.0 - GOVERNANCE_WARNING_PENALTY * sum(f.severity == "warning" for f in flags))


def dimension_scores(
    values: dict[str, float | None], sector_group: str, flags: list[GovernanceFlag]
) -> tuple[dict[str, float], list[str]]:
    group = FINANCIAL if sector_group == FINANCIAL else "non_financial"
    scores: dict[str, float] = {}
    missing: list[str] = []
    for dim, by_group in COMPONENTS.items():
        parts = [governance_events_score(flags)] if dim == "management_governance" else []
        for metric, worst, best in by_group[group]:
            v = values.get(metric)
            if v is None and metric.endswith("_vs_sector") and values.get(metric.removesuffix("_vs_sector")) is not None:
                # Lack of sector peers is a gap in the peer set, not in the company's data: skip, don't zero.
                missing.append(f"{dim}.{metric} (no sector peers)")
            elif v is None and metric in NOT_PENALIZED:
                missing.append(f"{dim}.{metric} ({NOT_PENALIZED[metric]})")
            elif v is None:
                missing.append(f"{dim}.{metric}")
                parts.append(0.0)
            else:
                parts.append(scale(v, worst, best))
        scores[dim] = round(sum(parts) / len(parts), 1) if parts else 0.0
    if any(f.severity == "serious" for f in flags):
        scores["management_governance"] = 0.0
    return scores, missing


# ---------------------------------------------------------------- medium-term horizon (1-3 years)

# (latest-quarter metric, latest-year fallback, worst, best)
OUTLOOK_COMPONENTS = [
    ("revenue_growth_q_yoy", "revenue_growth_latest", -0.05, 0.25),
    ("profit_growth_q_yoy", "profit_growth_latest", -0.10, 0.30),
]
ACCELERATION = (-0.15, 0.15)  # change in profit growth, worst/best


def catalyst_signals(
    announcements: list[Announcement], as_of: date, industry_improving: bool, cfg: MediumTermCfg
) -> tuple[float, list[dict]]:
    """Evidenced catalysts only: filings in the lookback window, plus an improving industry. Never inferred."""
    since = as_of - timedelta(days=cfg.catalyst_lookback_days)
    found: dict[str, dict] = {}
    for a in sorted(announcements, key=lambda a: a.published_at, reverse=True):
        if a.category in cfg.catalyst_categories and since <= a.published_at.date() <= as_of and a.category not in found:
            found[a.category] = {"kind": a.category, "date": a.published_at.date().isoformat(), "title": a.title,
                                 "evidence_key": a.source.key}  # fmt: skip
    items = list(found.values())
    score = cfg.catalyst_points * len(items)
    if industry_improving:
        items.append({"kind": "industry_tailwind", "title": "Industry earnings improving across listed peers"})
        score += cfg.industry_tailwind_points
    return min(100.0, score), items


def medium_term_scores(
    values: dict[str, float | None], long_dims: dict[str, float], catalyst_score: float
) -> tuple[dict[str, float], list[str], str]:
    """Returns (category scores, missing components, earnings basis: 'quarterly' or 'annual')."""
    missing: list[str] = []
    quarterly = values.get("profit_growth_q_yoy") is not None
    parts = []
    for q_metric, fy_metric, worst, best in OUTLOOK_COMPONENTS:
        v = values.get(q_metric) if quarterly else values.get(fy_metric)
        if v is None:
            missing.append(f"earnings_outlook.{q_metric if quarterly else fy_metric}")
            parts.append(0.0)
        else:
            parts.append(scale(v, worst, best))
    now, before = ((values.get("profit_growth_q_yoy"), values.get("profit_growth_q_yoy_prev")) if quarterly
                   else (values.get("profit_growth_latest"), values.get("profit_cagr")))  # fmt: skip
    if now is None or before is None:
        missing.append("earnings_outlook.acceleration")
        parts.append(0.0)
    else:
        parts.append(scale(now - before, *ACCELERATION))
    dims = {
        "business_financial_quality": round((long_dims["business_quality"] + long_dims["financial_performance"]) / 2, 1),
        "earnings_outlook": round(sum(parts) / len(parts), 1),
        "financial_strength": long_dims["financial_strength"],
        "valuation": long_dims["valuation"],
        "catalysts": round(catalyst_score, 1),
        "management_risk": long_dims["management_governance"],
    }
    return dims, missing, "quarterly" if quarterly else "annual"


def weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    return round(sum(scores.get(dim, 0.0) * w for dim, w in weights.items()), 1)


def evaluate_candidate(
    symbol: str,
    values: dict[str, float | None],
    dq: DataQualityReport,
    sector_group: str,
    flags: list[GovernanceFlag],
    rules: list[RuleResult],
    cfg: ScreeningConfig,
    catalysts: tuple[float, list[dict]] = (0.0, []),
) -> CandidateEvaluation:
    if not dq.is_eligible:
        return CandidateEvaluation(
            symbol=symbol, status="ineligible", rule_results=rules, governance_flags=flags,
            exclusion_reasons=[f"data: {i.message}" for i in dq.errors],
        )  # fmt: skip

    scores, missing = dimension_scores(values, sector_group, flags)
    total = weighted_score(scores, cfg.scoring.weights_for(sector_group))
    mt_scores, mt_missing, basis = medium_term_scores(values, scores, catalysts[0])
    mt_total = weighted_score(mt_scores, cfg.horizons.medium_term.weights)
    reasons: list[str] = []
    status = "candidate"

    serious = [f for f in flags if f.severity == "serious"]
    if serious:
        status = "governance_review"
        reasons += [f"governance: {f.message}" for f in serious]

    hard_fails = [r for r in rules if r.hard and r.status in ("fail", "missing") and r.stage != "governance"]
    if hard_fails:
        status = "rejected" if status == "candidate" else status
        reasons += [f"{r.rule_id}: {r.message}" for r in hard_fails]

    return CandidateEvaluation(
        symbol=symbol, status=status, score=total, dimension_scores=scores, missing_components=missing,
        rule_results=rules, governance_flags=flags, exclusion_reasons=reasons,
        horizon_scores={"long_term": total, "medium_term": mt_total}, medium_term_scores=mt_scores,
        medium_term_missing=mt_missing, earnings_basis=basis, catalysts=catalysts[1],
    )  # fmt: skip
