"""Fundamentals from Screener.in public company pages (a SECONDARY aggregator of company filings).

One page per company gives annual P&L, balance sheet, cash flow, ratios, the last ~12 quarters, shareholding,
market cap, and sector/industry classification. Every value is tagged with the page URL as its source and
reports flag the data as secondary, to be verified against filings for material decisions.

Fetching goes through PoliteHttpClient (honest User-Agent, robots.txt, rate limit, cache). Check Screener's
terms of use for your own usage.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from app.infra.http_client import FetchError, NotFound, PoliteHttpClient
from app.schemas.market_data import (
    CompanyProfile,
    Consolidation,
    FinancialStatements,
    FinancialValue,
    PeriodType,
    Shareholding,
    SourceRef,
)
from app.services.data.providers.base import DataNotAvailable, ProviderError

BASE_URL = "https://www.screener.in/company/{code}/{variant}"
_MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}

# label (normalized) -> canonical metric
PNL_MAP = {
    "sales": "revenue", "revenue": "revenue", "operating profit": "operating_profit", "other income": "other_income",
    "interest": "interest", "depreciation": "depreciation", "profit before tax": "pbt", "net profit": "net_profit",
}  # fmt: skip
BS_MAP = {"borrowings": "total_debt", "borrowing": "total_debt", "total assets": "total_assets", "deposits": "deposits"}
CF_MAP = {"cash from operating activity": "cfo"}
QUARTER_MAP = {**PNL_MAP, "gross npa %": "gross_npa_pct", "net npa %": "net_npa_pct"}


@dataclass
class Table:
    headers: list[str]  # column labels, first (row label) column excluded
    rows: dict[str, list[float | None]]


@dataclass
class ScreenerPage:
    name: str | None
    tables: dict[str, Table] = field(default_factory=dict)
    shareholding: Table | None = None
    top_ratios: dict[str, list[float | None]] = field(default_factory=dict)
    classification: dict[str, str] = field(default_factory=dict)  # Broad Sector / Sector / Broad Industry / Industry

    def has_annual_data(self) -> bool:
        pnl = self.tables.get("profit-loss")
        return bool(pnl and any(v is not None for vals in pnl.rows.values() for v in vals))


# ------------------------------------------------------------------------------------------- parsing (pure)


def _norm_label(text: str) -> str:
    text = text.replace("\xa0", " ").replace("+", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_number(text: str) -> float | None:
    t = text.replace(",", "").replace("%", "").replace("₹", "").strip()
    if t in ("", "-", "--"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_table(table: Tag) -> Table:
    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")][1:]
    rows: dict[str, list[float | None]] = {}
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = _norm_label(cells[0].get_text(" ", strip=True))
        if label and label not in rows:
            rows[label] = [parse_number(c.get_text(" ", strip=True)) for c in cells[1:]]
    return Table(headers=headers, rows=rows)


def parse_page(html: str) -> ScreenerPage:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    page = ScreenerPage(name=h1.get_text(" ", strip=True) if h1 else None)
    for sec in ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"):
        section = soup.find("section", id=sec)
        table = section.find("table") if section else None
        if table:
            page.tables[sec] = _parse_table(table)
    shp = soup.find(id="quarterly-shp")
    if shp and (table := shp.find("table")):
        page.shareholding = _parse_table(table)
    for li in soup.select("#top-ratios li"):
        name = li.find(class_="name")
        if name:
            page.top_ratios[_norm_label(name.get_text(" ", strip=True))] = [
                parse_number(n.get_text(" ", strip=True)) for n in li.find_all(class_="number")
            ]
    peers = soup.find("section", id="peers")
    if peers:
        for a in peers.select("p.sub a[title]"):
            page.classification[a["title"]] = a.get_text(" ", strip=True)
    return page


def parse_period_label(label: str) -> date | None:
    """'Mar 2026' -> 2026-03-31. Returns None for 'TTM' and anything unrecognised."""
    m = re.fullmatch(r"([A-Za-z]{3})\s+(\d{4})", label.strip())
    if not m or m.group(1).title() not in _MONTHS:
        return None
    year, month = int(m.group(2)), _MONTHS[m.group(1).title()]
    return date(year, month, calendar.monthrange(year, month)[1])


def fy_period(end: date) -> str:
    return f"FY{end.year}"


def quarter_period(end: date) -> str:
    """Indian fiscal quarters (FY ends March): Jun=Q1, Sep=Q2, Dec=Q3, Mar=Q4."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(end.month)
    if q is None:
        return f"Q-{end:%Y-%m}"
    return f"Q{q}FY{end.year + 1 if end.month > 3 else end.year}"


def build_statements(
    page: ScreenerPage, symbol: str, source: SourceRef, consolidation: Consolidation
) -> tuple[FinancialStatements, bool]:
    """Returns (statements, is_lender)."""
    values: list[FinancialValue] = []
    pnl = page.tables.get("profit-loss")
    if pnl is None:
        return FinancialStatements(symbol=symbol, sources={source.key: source}), False
    is_lender = "financing profit" in pnl.rows

    annual_cols = {i: d for i, h in enumerate(pnl.headers) if (d := parse_period_label(h))}
    annual_periods = {d: fy_period(d) for d in annual_cols.values()}

    def emit(table: Table | None, mapping: dict[str, str], col_filter: set[date], period_type: PeriodType, namer):
        found: dict[tuple[date, str], float] = {}
        if table is None:
            return found
        for i, header in enumerate(table.headers):
            end = parse_period_label(header)
            if end is None or end not in col_filter:
                continue
            for label, metric in mapping.items():
                row = table.rows.get(label)
                if row is None or i >= len(row) or row[i] is None:
                    continue
                found[(end, metric)] = row[i]
                values.append(FinancialValue(period=namer(end), period_end=end, period_type=period_type, metric=metric,
                                             value=row[i], unit="pct" if metric.endswith("_pct") else "INR_crore",
                                             consolidation=consolidation, source_key=source.key))  # fmt: skip
        return found

    fy_ends = set(annual_periods)
    annual = emit(pnl, PNL_MAP, fy_ends, PeriodType.FY, fy_period)
    emit(page.tables.get("balance-sheet"), BS_MAP, fy_ends, PeriodType.FY, fy_period)
    emit(page.tables.get("cash-flow"), CF_MAP, fy_ends, PeriodType.FY, fy_period)

    bs = page.tables.get("balance-sheet")
    ratios = page.tables.get("ratios")
    for end in sorted(fy_ends):
        derived: dict[str, float] = {}
        if bs:
            cap, res = _cell(bs, "equity capital", end), _cell(bs, "reserves", end)
            if cap is not None and res is not None:
                derived["total_equity"] = cap + res
        rev = annual.get((end, "revenue"))
        if ratios and rev is not None and (dd := _cell(ratios, "debtor days", end)) is not None:
            derived["receivables"] = dd * rev / 365  # derived from Screener's debtor days
        if is_lender and rev is not None and (interest := annual.get((end, "interest"))) is not None:
            derived["net_interest_income"] = rev - interest
        for metric, v in derived.items():
            values.append(FinancialValue(period=fy_period(end), period_end=end, metric=metric, value=v,
                                         consolidation=consolidation, source_key=source.key))  # fmt: skip

    quarters = page.tables.get("quarters")
    if quarters:
        q_ends = {d for h in quarters.headers if (d := parse_period_label(h))}
        q_found = emit(quarters, QUARTER_MAP, q_ends, PeriodType.QUARTER, quarter_period)
        # Lenders report asset quality quarterly: carry the fiscal-year-end quarter into the FY record.
        for (end, metric), v in q_found.items():
            if metric.endswith("_npa_pct") and end in fy_ends:
                values.append(FinancialValue(period=fy_period(end), period_end=end, metric=metric, value=v, unit="pct",
                                             consolidation=consolidation, source_key=source.key))  # fmt: skip

    mcap = (page.top_ratios.get("market cap") or [None])[0]
    price = (page.top_ratios.get("current price") or [None])[0]
    shares = mcap / price if mcap and price else None
    return FinancialStatements(symbol=symbol, values=values, shares_outstanding_cr=shares, sources={source.key: source}), is_lender


def _cell(table: Table, label: str, end: date) -> float | None:
    row = table.rows.get(label)
    if row is None:
        return None
    for i, h in enumerate(table.headers):
        if parse_period_label(h) == end and i < len(row):
            return row[i]
    return None


def build_shareholding(page: ScreenerPage, symbol: str, url: str, retrieved_at: datetime) -> list[Shareholding]:
    t = page.shareholding
    if t is None or "promoters" not in t.rows:
        return []
    out = []
    for i, header in enumerate(t.headers):
        end = parse_period_label(header)
        value = t.rows["promoters"][i] if i < len(t.rows["promoters"]) else None
        if end is None or value is None:
            continue
        out.append(Shareholding(period_end=end, promoter_holding_pct=value, source=SourceRef(
            key=f"{symbol}:shareholding:{end}", provider="screener", source_type="secondary_aggregator", url=url,
            title=f"Shareholding pattern {end} (via Screener.in)", retrieved_at=retrieved_at)))  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------- provider


class ScreenerProvider:
    name = "screener"

    def __init__(self, client: PoliteHttpClient, cache_hours: float = 72.0):
        self.client = client
        self.ttl = cache_hours * 3600
        self._pages: dict[str, tuple[ScreenerPage, str, datetime, Consolidation]] = {}

    def _fetch(self, url: str):
        try:
            return self.client.get(url, ttl_seconds=self.ttl)
        except NotFound as e:
            raise DataNotAvailable(f"not on Screener: {url}") from e
        except FetchError as e:  # includes AccessDenied
            raise ProviderError(str(e)) from e

    def _page(self, symbol: str) -> tuple[ScreenerPage, str, datetime, Consolidation]:
        if symbol not in self._pages:
            url = BASE_URL.format(code=symbol, variant="consolidated/")
            res = self._fetch(url)
            page, consolidation = parse_page(res.content.decode("utf-8", errors="replace")), Consolidation.CONSOLIDATED
            if not page.has_annual_data():  # company doesn't publish consolidated accounts
                url = BASE_URL.format(code=symbol, variant="")
                res = self._fetch(url)
                page, consolidation = parse_page(res.content.decode("utf-8", errors="replace")), Consolidation.STANDALONE
            if not page.has_annual_data():
                raise DataNotAvailable(f"{symbol}: Screener page has no financial data")
            self._pages[symbol] = (page, url, res.fetched_at, consolidation)
        return self._pages[symbol]

    def get_profile(self, symbol: str) -> CompanyProfile:
        page, *_ = self._page(symbol)
        c = page.classification
        return CompanyProfile(symbol=symbol, sector=c.get("Sector") or c.get("Broad Sector"),
                              industry=c.get("Broad Industry") or c.get("Industry"))  # fmt: skip

    def get_financials(self, symbol: str) -> FinancialStatements:
        page, url, fetched_at, consolidation = self._page(symbol)
        source = SourceRef(
            key=f"{symbol}:financials", provider=self.name, source_type="secondary_aggregator", url=url,
            title=f"Screener.in {consolidation.value} financials for {page.name or symbol}", retrieved_at=fetched_at,
        )  # fmt: skip
        return build_statements(page, symbol, source, consolidation)[0]

    def get_shareholding(self, symbol: str) -> list[Shareholding]:
        page, url, fetched_at, _ = self._page(symbol)
        return build_shareholding(page, symbol, url, fetched_at)
