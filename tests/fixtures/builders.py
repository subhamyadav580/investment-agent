"""Small builders for hand-made CompanyData in unit tests."""

from datetime import UTC, date, datetime, timedelta

from app.schemas.market_data import (
    Announcement,
    CompanyData,
    FinancialStatements,
    FinancialValue,
    PriceBar,
    PriceHistory,
    Shareholding,
    SourceRef,
)

RETRIEVED = datetime(2026, 10, 23, tzinfo=UTC)


def src(key: str = "T:fin", source_type: str = "annual_report") -> SourceRef:
    return SourceRef(key=key, provider="test", source_type=source_type, retrieved_at=RETRIEVED)


def statements(annual: dict[int, dict[str, float | None]], shares: float | None = 10.0, symbol="TEST") -> FinancialStatements:
    s = src()
    values = [
        FinancialValue(period=f"FY{y}", period_end=date(y, 3, 31), metric=m, value=v, source_key=s.key)
        for y, metrics in annual.items()
        for m, v in metrics.items()
    ]
    return FinancialStatements(symbol=symbol, values=values, shares_outstanding_cr=shares, sources={s.key: s})


def prices(last: date, close: float, days: int = 400, volume: float = 1_000_000) -> PriceHistory:
    bars = [PriceBar(date=last - timedelta(days=i), close=close, volume=volume) for i in range(days)][::-1]
    return PriceHistory(symbol="TEST", bars=bars, source=src("T:prices", "price_feed"))


def announcement(category: str, published: date, title="event", event_date: date | None = None) -> Announcement:
    return Announcement(
        id=f"{category}-{published}", symbol="TEST", category=category, title=title,
        published_at=datetime(published.year, published.month, published.day, tzinfo=UTC), event_date=event_date,
        source=src(f"T:ann:{category}:{published}", "exchange_filing"),
    )  # fmt: skip


def shareholding(period_end: date, promoter: float, pledged: float) -> Shareholding:
    return Shareholding(
        period_end=period_end, promoter_holding_pct=promoter, promoter_pledged_pct=pledged,
        source=src(f"T:sh:{period_end}", "shareholding_pattern"),
    )  # fmt: skip


def healthy_annual(years=range(2021, 2027), rev0=1000.0, growth=0.12) -> dict[int, dict[str, float]]:
    out, rev, eq = {}, rev0, 800.0
    for y in years:
        np_ = rev * 0.12
        eq += np_ * 0.8
        out[y] = {
            "revenue": rev, "operating_profit": rev * 0.2, "pbt": rev * 0.16, "interest": 10.0, "net_profit": np_,
            "total_equity": eq, "total_debt": 100.0, "cash_and_equivalents": 50.0, "cfo": np_ * 0.95,
            "receivables": rev * 50 / 365,
        }  # fmt: skip
        rev *= 1 + growth
    return out


def company_data(annual=None, price=None, **kw) -> CompanyData:
    annual = healthy_annual() if annual is None else annual
    return CompanyData(
        symbol="TEST",
        financials=statements(annual) if annual else None,
        prices=price if price is not None else prices(date(2026, 10, 23), 300.0),
        **kw,
    )
