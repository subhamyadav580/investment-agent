"""Explainable 0-100 research-priority score (plan 5.5). This prioritizes research; it does not predict returns.

- Each dimension is the mean of linearly-scaled components.
- A missing component scores 0 and is reported in `missing_components` - it never gets a free pass.
- Serious governance flags do not get averaged away: they set status=governance_review.
"""

from app.schemas.market_data import DataQualityReport
from app.schemas.screening import CandidateEvaluation, GovernanceFlag, RuleResult
from app.services.discovery.rules_config import ScreeningConfig
from app.services.discovery.sector_classifier import FINANCIAL

# (metric, worst, best): linear from 0 at `worst` to 100 at `best` (works for inverse metrics too)
Component = tuple[str, float, float]

COMPONENTS: dict[str, dict[str, list[Component]]] = {
    "business_quality": {
        "non_financial": [("roce_latest", 0.05, 0.30), ("roce_avg_3y", 0.05, 0.30),
                          ("operating_margin_avg", 0.03, 0.25), ("operating_margin_stdev", 0.08, 0.01)],
        FINANCIAL: [("roe_latest", 0.05, 0.20), ("roe_avg_3y", 0.05, 0.20), ("roa_latest", 0.003, 0.02)],
    },
    "growth_consistency": {
        "non_financial": [("revenue_cagr", 0.0, 0.20), ("profit_cagr", 0.0, 0.25), ("profit_positive_ratio", 0.4, 1.0)],
        FINANCIAL: [("revenue_cagr", 0.0, 0.20), ("profit_cagr", 0.0, 0.25), ("profit_positive_ratio", 0.4, 1.0)],
    },
    "financial_health": {
        "non_financial": [("debt_to_equity", 2.0, 0.0), ("interest_coverage", 1.5, 10.0), ("cfo_to_pat_3y", 0.3, 1.0)],
        FINANCIAL: [("capital_adequacy_ratio", 11.0, 20.0), ("gross_npa_pct", 8.0, 1.0)],
    },
    "valuation": {
        "non_financial": [("pe_vs_sector", 2.0, 0.6), ("pe", 60.0, 10.0), ("ev_ebitda", 35.0, 8.0)],
        FINANCIAL: [("pb_vs_sector", 2.0, 0.6), ("pb", 5.0, 1.0)],
    },
}  # fmt: skip

GOVERNANCE_WARNING_PENALTY = 25.0


def scale(value: float, worst: float, best: float) -> float:
    if best == worst:
        return 100.0
    return max(0.0, min(100.0, (value - worst) / (best - worst) * 100.0))


def dimension_scores(
    values: dict[str, float | None], sector_group: str, dq: DataQualityReport, flags: list[GovernanceFlag]
) -> tuple[dict[str, float], list[str]]:
    group = FINANCIAL if sector_group == FINANCIAL else "non_financial"
    scores: dict[str, float] = {}
    missing: list[str] = []
    for dim, by_group in COMPONENTS.items():
        parts = []
        for metric, worst, best in by_group[group]:
            v = values.get(metric)
            if v is None and metric.endswith("_vs_sector") and values.get(metric.removesuffix("_vs_sector")) is not None:
                # Lack of sector peers is a gap in the peer set, not in the company's data: skip, don't zero.
                missing.append(f"{dim}.{metric} (no sector peers)")
            elif v is None:
                missing.append(f"{dim}.{metric}")
                parts.append(0.0)
            else:
                parts.append(scale(v, worst, best))
        scores[dim] = round(sum(parts) / len(parts), 1) if parts else 0.0

    warnings = sum(f.severity == "warning" for f in flags)
    serious = any(f.severity == "serious" for f in flags)
    gov = 0.0 if serious else max(0.0, dq.score - GOVERNANCE_WARNING_PENALTY * warnings)
    scores["governance_data_quality"] = round(gov, 1)
    return scores, missing


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
) -> CandidateEvaluation:
    if not dq.is_eligible:
        return CandidateEvaluation(
            symbol=symbol, status="ineligible", rule_results=rules, governance_flags=flags,
            exclusion_reasons=[f"data: {i.message}" for i in dq.errors],
        )  # fmt: skip

    scores, missing = dimension_scores(values, sector_group, dq, flags)
    total = weighted_score(scores, cfg.scoring.weights)
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
    )  # fmt: skip
