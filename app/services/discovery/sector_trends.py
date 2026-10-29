"""Sector/industry discovery (plan source D): which industries show improving earnings right now.

Uses each company's latest-quarter YoY growth. An industry is "improving" when its median latest-quarter
profit growth is positive, accelerating versus the previous quarter, and broad-based (at least half of its
companies growing). This only nudges research priority; it never changes a company's score or rules.
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable

from app.services.discovery.company_evaluator import PreparedCompany


def industry_of(p: PreparedCompany) -> str | None:
    return (p.data.profile.industry if p.data.profile else None) or p.sector


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 4) if xs else None


def compute_industry_trends(prepared: Iterable[PreparedCompany], min_companies: int) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in prepared:
        if p.data_quality.is_eligible and (ind := industry_of(p)):
            groups[ind].append(p.values)
    out = {}
    for industry, vals in groups.items():
        if len(vals) < min_companies:
            continue
        rev = [v["revenue_growth_q_yoy"] for v in vals if v.get("revenue_growth_q_yoy") is not None]
        prof = [v["profit_growth_q_yoy"] for v in vals if v.get("profit_growth_q_yoy") is not None]
        prev = [v["profit_growth_q_yoy_prev"] for v in vals if v.get("profit_growth_q_yoy_prev") is not None]
        med, med_prev = _median(prof), _median(prev)
        breadth = round(sum(x > 0 for x in prof) / len(prof), 3) if prof else None
        improving = bool(
            med is not None and med > 0 and breadth is not None and breadth >= 0.5
            and (med_prev is None or med > med_prev)
        )  # fmt: skip
        out[industry] = {
            "companies": len(vals),
            "with_quarterly_data": len(prof),
            "median_revenue_growth_q_yoy": _median(rev),
            "median_profit_growth_q_yoy": med,
            "median_profit_growth_q_yoy_prev": med_prev,
            "breadth": breadth,
            "improving": improving,
        }
    return dict(sorted(out.items(), key=lambda kv: -(kv[1]["median_profit_growth_q_yoy"] or -9e9)))
