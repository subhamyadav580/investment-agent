"""Unit, period, and identifier normalization. Pure functions; no I/O."""

import re
from datetime import date, datetime
from typing import Any

from app.schemas.market_data import (
    Announcement,
    CompanyProfile,
    Consolidation,
    FinancialStatements,
    FinancialValue,
    Shareholding,
    SourceRef,
)

CANONICAL_UNIT = "INR_crore"

# multiplier to convert 1 unit into INR crore
_UNIT_TO_CRORE = {
    "inr_crore": 1.0,
    "crore": 1.0,
    "cr": 1.0,
    "inr_lakh": 0.01,
    "lakh": 0.01,
    "inr_million": 0.1,
    "million": 0.1,
    "mn": 0.1,
    "inr_billion": 100.0,
    "billion": 100.0,
    "inr": 1e-7,
    "rupees": 1e-7,
}

# Metrics that are ratios/percentages and must NOT be unit-converted.
PERCENT_METRICS = {"gross_npa_pct", "net_npa_pct", "capital_adequacy_ratio", "promoter_holding_pct"}


class UnknownUnitError(ValueError):
    pass


def to_crore(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    factor = _UNIT_TO_CRORE.get(unit.strip().lower())
    if factor is None:
        raise UnknownUnitError(f"unknown unit {unit!r}")
    return float(value) * factor


_FY_RE = re.compile(r"^(?:FY)?\s*'?(\d{2}|\d{4})$", re.IGNORECASE)
_MON_YEAR_RE = re.compile(r"^(?:Mar|March)[\s\-]*(\d{4})$", re.IGNORECASE)


def normalize_fy_period(label: str) -> tuple[str, date]:
    """'FY2026' | 'FY26' | '2026' | 'Mar 2026' | '2026-03' -> ('FY2026', 2026-03-31).

    Indian financial years end on 31 March; FY2026 = Apr 2025 - Mar 2026.
    """
    label = label.strip()
    m = _FY_RE.match(label) or _MON_YEAR_RE.match(label)
    if not m and re.match(r"^\d{4}-03(-31)?$", label):
        m = re.match(r"^(\d{4})", label)
    if not m:
        raise ValueError(f"unrecognised financial-year label {label!r}")
    year = int(m.group(1))
    if year < 100:
        year += 2000
    return f"FY{year}", date(year, 3, 31)


def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    for suffix in (".NS", ".BO", "-EQ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def parse_company_document(
    symbol: str,
    doc: dict[str, Any],
    *,
    provider: str,
    retrieved_at: datetime,
    is_synthetic: bool = False,
) -> tuple[CompanyProfile, FinancialStatements, list[Shareholding], list[Announcement]]:
    """Parse the provider-neutral company JSON document (see docs in data/local/README.md)."""
    unit = doc.get("unit", CANONICAL_UNIT)
    consolidation = Consolidation(doc.get("consolidation", "consolidated"))
    src_meta = doc.get("source", {})
    primary = SourceRef(
        key=f"{symbol}:financials",
        provider=provider,
        source_type=src_meta.get("source_type", "annual_report"),
        url=src_meta.get("url"),
        title=src_meta.get("title", f"{symbol} annual financials"),
        published_at=_parse_dt(src_meta.get("published_at")),
        retrieved_at=retrieved_at,
        is_synthetic=is_synthetic,
    )
    sources = {primary.key: primary}
    values: list[FinancialValue] = []
    for raw_period, metrics in doc.get("annual", {}).items():
        period, period_end = normalize_fy_period(raw_period)
        for metric, raw in metrics.items():
            value = raw if metric in PERCENT_METRICS else to_crore(raw, unit)
            values.append(
                FinancialValue(
                    period=period,
                    period_end=period_end,
                    metric=metric,
                    value=value,
                    unit="pct" if metric in PERCENT_METRICS else CANONICAL_UNIT,
                    consolidation=consolidation,
                    source_key=primary.key,
                )
            )
    # Alternative values for the same period/metric from a different source (cross-checks).
    for i, alt in enumerate(doc.get("alternate_values", [])):
        alt_src = SourceRef(
            key=f"{symbol}:alt:{i}",
            provider=provider,
            source_type=alt.get("source_type", "secondary"),
            url=alt.get("url"),
            title=alt.get("source_title", "secondary source"),
            retrieved_at=retrieved_at,
            is_synthetic=is_synthetic,
        )
        sources[alt_src.key] = alt_src
        period, period_end = normalize_fy_period(alt["period"])
        values.append(
            FinancialValue(
                period=period,
                period_end=period_end,
                metric=alt["metric"],
                value=to_crore(alt["value"], alt.get("unit", unit)),
                consolidation=Consolidation(alt.get("consolidation", consolidation)),
                source_key=alt_src.key,
            )
        )

    financials = FinancialStatements(
        symbol=symbol,
        values=values,
        shares_outstanding_cr=doc.get("shares_outstanding_cr"),
        sources=sources,
    )
    profile = CompanyProfile(symbol=symbol, sector=doc.get("sector"), industry=doc.get("industry"))

    shareholding = []
    for i, sh in enumerate(doc.get("shareholding", [])):
        src = SourceRef(
            key=f"{symbol}:shareholding:{i}",
            provider=provider,
            source_type="shareholding_pattern",
            url=sh.get("url"),
            title=f"{symbol} shareholding pattern {sh['period_end']}",
            retrieved_at=retrieved_at,
            is_synthetic=is_synthetic,
        )
        shareholding.append(
            Shareholding(
                period_end=date.fromisoformat(sh["period_end"]),
                promoter_holding_pct=sh.get("promoter_holding_pct"),
                promoter_pledged_pct=sh.get("promoter_pledged_pct"),
                source=src,
            )
        )
    shareholding.sort(key=lambda s: s.period_end)

    announcements = [parse_announcement(symbol, a, provider, retrieved_at, is_synthetic) for a in doc.get("announcements", [])]
    return profile, financials, shareholding, announcements


def parse_announcement(
    symbol: str, raw: dict[str, Any], provider: str, retrieved_at: datetime, is_synthetic: bool
) -> Announcement:
    published = _parse_dt(raw["published_at"])
    ann_id = raw.get("id") or f"{symbol}:{raw['category']}:{published.isoformat()}"
    return Announcement(
        id=ann_id,
        symbol=symbol,
        category=raw["category"],
        title=raw["title"],
        published_at=published,
        event_date=date.fromisoformat(raw["event_date"]) if raw.get("event_date") else None,
        summary=raw.get("summary"),
        source=SourceRef(
            key=f"{symbol}:announcement:{ann_id}",
            provider=provider,
            source_type="exchange_filing",
            url=raw.get("url"),
            title=raw["title"],
            published_at=published,
            retrieved_at=retrieved_at,
            is_synthetic=is_synthetic,
        ),
    )
