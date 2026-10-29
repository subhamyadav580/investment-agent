"""Data validation: freshness, completeness, units, periods, consolidation, and cross-source conflicts.

Produces a DataQualityReport. Errors make a company ineligible for scoring - the system never fills gaps.
"""

from collections import defaultdict
from datetime import date

from app.schemas.market_data import CompanyData, DataIssue, DataQualityReport, PeriodType
from app.services.data.normalization import CANONICAL_UNIT
from app.services.discovery.rules_config import EligibilityCfg
from app.services.discovery.sector_classifier import FINANCIAL

REQUIRED_FIELDS = {
    "non_financial": ["revenue", "operating_profit", "pbt", "net_profit", "interest", "total_equity",
                      "total_debt", "cfo"],
    FINANCIAL: ["revenue", "net_profit", "total_equity", "total_assets"],
}  # fmt: skip

_PENALTY = {"error": 35.0, "warning": 8.0, "info": 0.0}


def validate_company_data(
    data: CompanyData, sector_group: str, as_of: date, cfg: EligibilityCfg
) -> DataQualityReport:
    issues: list[DataIssue] = []
    add = lambda code, sev, msg, field=None: issues.append(  # noqa: E731
        DataIssue(code=code, severity=sev, message=msg, field=field)
    )

    for err in data.fetch_errors:
        add("provider_error", "warning", err)

    fin = data.financials
    if fin is None or not fin.values:
        add("no_financials", "error", "No financial statements available from the configured provider.")
        return _finish(issues, years=0)

    periods = fin.periods(PeriodType.FY)
    years = len(periods)
    latest = periods[-1] if periods else None
    latest_end = fin.period_end(latest) if latest else None

    if years < cfg.min_years:
        add("insufficient_history", "error", f"{years} year(s) of annual data; minimum is {cfg.min_years}.")
    elif years < cfg.preferred_years:
        add("short_history", "warning", f"{years} years of annual data; {cfg.preferred_years} preferred.")

    if latest_end and (as_of - latest_end).days > cfg.max_financials_age_days:
        add("stale_financials", "error",
            f"Latest annual period {latest} ended {latest_end}, {(as_of - latest_end).days} days before {as_of}.")  # fmt: skip

    # Gaps in the FY sequence (e.g. FY2022 missing between FY2021 and FY2023)
    fy_years = sorted(int(p[2:]) for p in periods)
    for prev, nxt in zip(fy_years, fy_years[1:], strict=False):
        if nxt - prev > 1:
            add("missing_period", "warning", f"No data between FY{prev} and FY{nxt}.")

    required = REQUIRED_FIELDS.get(sector_group, REQUIRED_FIELDS["non_financial"])
    for metric in required:
        series = fin.series(metric)
        if latest and series.get(latest) is None:
            add("missing_required_field", "error", f"{metric} missing for latest period {latest}.", metric)
        elif sum(v is None for v in series.values()) or len(series) < years:
            add("missing_historical_field", "warning", f"{metric} missing for some earlier periods.", metric)

    bad_units = {v.unit for v in fin.values if v.unit not in (CANONICAL_UNIT, "pct")}
    if bad_units:
        add("unit_mismatch", "error", f"Values in non-canonical units: {sorted(bad_units)}.")

    consolidations = {v.consolidation for v in fin.values if v.source_key in fin.sources}
    if len(consolidations) > 1:
        add("mixed_consolidation", "warning",
            "Mix of consolidated and standalone figures; comparisons across years may be inconsistent.")  # fmt: skip

    issues.extend(_conflicts(data, cfg.conflict_tolerance))

    if latest:
        rev = fin.series("revenue").get(latest)
        if rev is not None and rev <= 0:
            add("non_positive_revenue", "error", f"Revenue for {latest} is {rev}.", "revenue")
        eq = fin.series("total_equity").get(latest)
        if eq is not None and eq <= 0:
            add("negative_equity", "warning", f"Total equity for {latest} is {eq}; return ratios unreliable.")

    issues.extend(_implausible_jumps(fin, latest))

    if fin.shares_outstanding_cr is None:
        add("missing_share_count", "warning", "Shares outstanding unknown; market-cap based valuation unavailable.")

    if data.prices is None or not data.prices.bars:
        add("no_price_data", "warning", "No price history; valuation and liquidity checks unavailable.")
    else:
        age = (as_of - data.prices.bars[-1].date).days
        if age > cfg.max_price_age_days:
            add("stale_prices", "warning", f"Last price is {age} days old ({data.prices.bars[-1].date}).")

    if any(s.source_type == "secondary_aggregator" for s in fin.sources.values()):
        add("secondary_source", "info",
            "Financials come from a secondary aggregator (Screener.in). Verify material figures against the "
            "company's filings before relying on them.")  # fmt: skip
    if any(s.is_synthetic for s in data.all_sources().values()):
        add("synthetic_data", "info", "Includes SYNTHETIC sample data - not real company figures.")

    return _finish(
        issues,
        years=years,
        latest=latest,
        latest_end=latest_end,
        consolidation=next(iter(consolidations)).value if len(consolidations) == 1 else "mixed",
    )


def _conflicts(data: CompanyData, tolerance: float) -> list[DataIssue]:
    by_key: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for v in data.financials.values:
        if v.value is not None:
            by_key[(v.period, v.metric)].append((v.source_key, v.value))
    out = []
    for (period, metric), vals in by_key.items():
        if len({s for s, _ in vals}) < 2:
            continue
        nums = [x for _, x in vals]
        base = max(abs(n) for n in nums) or 1.0
        if (max(nums) - min(nums)) / base > tolerance:
            out.append(
                DataIssue(
                    code="conflicting_values",
                    severity="warning",
                    message=f"{metric} {period}: sources disagree ({', '.join(f'{s}={x:g}' for s, x in vals)}).",
                    field=metric,
                )
            )
    return out


def _finish(issues, years, latest=None, latest_end=None, consolidation=None) -> DataQualityReport:
    score = max(0.0, 100.0 - sum(_PENALTY[i.severity] for i in issues))
    return DataQualityReport(
        is_eligible=not any(i.severity == "error" for i in issues),
        score=round(score, 1),
        years_available=years,
        latest_period=latest,
        latest_period_end=latest_end,
        consolidation=consolidation,
        issues=issues,
    )


OUTLIER_MULTIPLE = 3.0


def _implausible_jumps(fin, latest: str | None) -> list[DataIssue]:
    """Values that are arithmetically possible but unusual enough to need a human look before trusting ratios
    built on them (e.g. a one-off customer advance inflating operating cash flow)."""
    if not latest:
        return []
    out = []
    v = lambda m, p=latest: fin.series(m).get(p)  # noqa: E731
    cfo, op, pat = v("cfo"), v("operating_profit"), v("net_profit")
    base = max(abs(op or 0), abs(pat or 0))
    if cfo is not None and base > 0 and abs(cfo) > OUTLIER_MULTIPLE * base:
        out.append(DataIssue(code="cash_flow_outlier", severity="warning", field="cfo",
                             message=f"Operating cash flow {latest} ({cfo:,.0f}) is {abs(cfo) / base:.1f}x operating "
                                     "profit; likely a one-off (advances, working-capital swing). Cash-conversion "
                                     "ratios are distorted - check the cash flow statement."))  # fmt: skip
    periods = fin.periods()
    if len(periods) >= 2:
        prev = periods[-2]
        for metric in ("total_assets", "total_debt", "revenue"):
            a, b = v(metric, prev), v(metric, latest)
            if a and b and a > 0 and b / a > OUTLIER_MULTIPLE:
                out.append(DataIssue(code="balance_jump", severity="warning", field=metric,
                                     message=f"{metric} rose {b / a:.1f}x from {prev} to {latest}; check for "
                                             "acquisitions, fund-raising, or a data error."))  # fmt: skip
    return out
