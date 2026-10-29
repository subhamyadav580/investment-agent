"""Deterministic, sector-aware screening rules (plan stages 1-4). Each rule explains its own outcome.

A rule whose input is missing returns status="missing" - missing data never passes.
"""

from collections.abc import Callable
from datetime import date, timedelta

from app.schemas.market_data import CompanyData, DataQualityReport
from app.schemas.screening import GovernanceFlag, RuleResult
from app.services.discovery.rules_config import GovernanceCfg, ScreeningConfig
from app.services.discovery.sector_classifier import FINANCIAL


def derived_values(
    values: dict[str, float | None], sector_medians: dict[str, float] | None
) -> dict[str, float | None]:
    """Relative-valuation ratios that depend on peers. Added to the metric values used by rules and scoring."""
    out = dict(values)
    medians = sector_medians or {}
    for k in ("pe", "pb"):
        v, m = values.get(k), medians.get(k)
        out[f"{k}_vs_sector"] = (v / m) if v is not None and m else None
    return out


# --------------------------------------------------------------------------- governance


def detect_governance_flags(data: CompanyData, as_of: date, cfg: GovernanceCfg) -> list[GovernanceFlag]:
    flags: list[GovernanceFlag] = []
    since = as_of - timedelta(days=cfg.lookback_days)
    for a in data.announcements:
        if a.published_at.date() < since or a.published_at.date() > as_of:
            continue
        if a.category in cfg.serious_flags or a.category in cfg.warning_flags:
            severity = "serious" if a.category in cfg.serious_flags else "warning"
            flags.append(
                GovernanceFlag(code=a.category, severity=severity, message=f"{a.published_at.date()}: {a.title}",
                               evidence_key=a.source.key)  # fmt: skip
            )

    holdings = [s for s in data.shareholding if s.period_end <= as_of]
    if holdings:
        latest = holdings[-1]
        pledged = latest.promoter_pledged_pct
        if pledged is not None and pledged >= cfg.pledge_serious_pct:
            flags.append(GovernanceFlag(code="promoter_pledge_high", severity="serious",
                                        message=f"{pledged:.1f}% of promoter holding pledged ({latest.period_end}).",
                                        evidence_key=latest.source.key))  # fmt: skip
        elif pledged is not None and pledged >= cfg.pledge_warning_pct:
            flags.append(GovernanceFlag(code="promoter_pledge_elevated", severity="warning",
                                        message=f"{pledged:.1f}% of promoter holding pledged ({latest.period_end}).",
                                        evidence_key=latest.source.key))  # fmt: skip
        year_ago = [s for s in holdings if s.period_end <= latest.period_end - timedelta(days=330)]
        if year_ago and latest.promoter_holding_pct is not None and year_ago[-1].promoter_holding_pct is not None:
            drop = year_ago[-1].promoter_holding_pct - latest.promoter_holding_pct
            if drop >= cfg.promoter_drop_warning_pp:
                flags.append(GovernanceFlag(code="promoter_holding_drop", severity="warning",
                                            message=f"Promoter holding fell {drop:.1f} pp in a year.",
                                            evidence_key=latest.source.key))  # fmt: skip
    return flags


# --------------------------------------------------------------------------- rules


def _threshold_rule(
    rule_id: str, stage: str, value: float | None, threshold: float, op: str, label: str, hard: bool = False,
    fmt: Callable[[float], str] = lambda x: f"{x:.2f}",
) -> RuleResult:  # fmt: skip
    if value is None:
        return RuleResult(rule_id=rule_id, stage=stage, status="missing", hard=hard, threshold=threshold,
                          message=f"{label}: data not available, rule cannot pass.")  # fmt: skip
    ok = value >= threshold if op == ">=" else value <= threshold
    return RuleResult(
        rule_id=rule_id, stage=stage, status="pass" if ok else "fail", hard=hard, observed=round(value, 4),
        threshold=threshold, message=f"{label} {fmt(value)} {'meets' if ok else 'breaches'} {op} {fmt(threshold)}.",
    )  # fmt: skip


def _na(rule_id: str, stage: str, why: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, stage=stage, status="not_applicable", message=why)


pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731


def evaluate_rules(
    values: dict[str, float | None],
    dq: DataQualityReport,
    sector_group: str,
    flags: list[GovernanceFlag],
    cfg: ScreeningConfig,
) -> list[RuleResult]:
    q, v = cfg.quality, cfg.valuation
    fin = sector_group == FINANCIAL
    r: list[RuleResult] = []

    # Stage 1 - data eligibility
    if dq.is_eligible:
        r.append(RuleResult(rule_id="data_eligible", stage="eligibility", status="pass", hard=True,
                            observed=dq.score, message=f"Data usable ({dq.years_available} years, quality {dq.score})."))  # fmt: skip
    else:
        r.append(RuleResult(rule_id="data_eligible", stage="eligibility", status="fail", hard=True,
                            observed=dq.score, message="; ".join(i.message for i in dq.errors)))  # fmt: skip
        return r  # nothing else is meaningful on unusable data

    # Stage 2 - financial quality
    r.append(_threshold_rule("revenue_growth", "quality", values.get("revenue_cagr"), q.min_revenue_cagr, ">=",
                             "Revenue CAGR", fmt=pct))  # fmt: skip
    r.append(_threshold_rule("profit_consistency", "quality", values.get("profit_positive_ratio"),
                             q.min_profit_positive_ratio, ">=", "Share of profitable years", fmt=pct))  # fmt: skip
    if fin:
        r.append(_threshold_rule("return_on_equity", "quality", values.get("roe_latest"), q.min_roe_financial, ">=",
                                 "ROE", fmt=pct))  # fmt: skip
        if values.get("gross_npa_pct") is not None:
            r.append(_threshold_rule("asset_quality", "quality", values.get("gross_npa_pct"), q.max_gross_npa_pct,
                                     "<=", "Gross NPA %"))  # fmt: skip
        else:
            r.append(RuleResult(rule_id="asset_quality", stage="quality", status="missing",
                                message="Gross NPA not reported; asset quality unverified."))  # fmt: skip
        for rid in ("leverage", "interest_coverage", "cash_conversion"):
            r.append(_na(rid, "quality", "Not meaningful for lenders; leverage/cash flow are part of the business."))
    else:
        r.append(_threshold_rule("return_on_capital", "quality", values.get("roce_latest"), q.min_roce, ">=", "ROCE",
                                 fmt=pct))  # fmt: skip
        r.append(_threshold_rule("leverage", "quality", values.get("debt_to_equity"), q.max_debt_to_equity, "<=",
                                 "Debt/equity"))  # fmt: skip
        r.append(_threshold_rule("interest_coverage", "quality", values.get("interest_coverage"),
                                 q.min_interest_coverage, ">=", "Interest coverage"))  # fmt: skip
        r.append(_threshold_rule("interest_coverage_critical", "quality", values.get("interest_coverage"),
                                 q.critical_interest_coverage, ">=", "Interest coverage (critical floor)", hard=True))  # fmt: skip
        r.append(_threshold_rule("cash_conversion", "quality", values.get("cfo_to_pat_3y"), q.min_cfo_to_pat, ">=",
                                 "3y operating cash flow / profit", fmt=pct))  # fmt: skip

    r.append(_threshold_rule("liquidity", "liquidity", values.get("avg_traded_value_cr_60d"),
                             cfg.liquidity.min_avg_traded_value_cr, ">=", "Avg daily traded value (INR cr)",
                             hard=True))  # fmt: skip

    # Stage 3 - valuation (flags, not hard fails: valuation alone shouldn't stop research)
    if fin:
        r.append(_threshold_rule("pb_absolute", "valuation", values.get("pb"), v.max_pb_financial, "<=", "P/B"))
    else:
        r.append(_threshold_rule("pe_absolute", "valuation", values.get("pe"), v.max_pe_absolute, "<=", "P/E"))
        if values.get("pe_vs_sector") is None and values.get("pe") is not None:
            r.append(_na("pe_vs_sector", "valuation", "No sector peers with P/E available."))
        else:
            r.append(_threshold_rule("pe_vs_sector", "valuation", values.get("pe_vs_sector"),
                                     v.max_pe_vs_sector_median, "<=", "P/E vs sector median"))  # fmt: skip

    # Stage 4 - governance
    serious = [f for f in flags if f.severity == "serious"]
    warnings = [f for f in flags if f.severity == "warning"]
    r.append(RuleResult(
        rule_id="governance_serious", stage="governance", status="flag" if serious else "pass", hard=bool(serious),
        observed=len(serious), message="; ".join(f.message for f in serious) or "No serious governance events found.",
    ))  # fmt: skip
    r.append(RuleResult(
        rule_id="governance_warnings", stage="governance", status="flag" if warnings else "pass",
        observed=len(warnings), message="; ".join(f.message for f in warnings) or "No governance warnings.",
    ))  # fmt: skip
    return r
