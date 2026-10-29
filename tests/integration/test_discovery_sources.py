"""Price sync, exchange price provider, universe merge, liquidity pre-filter, event discovery, industry trends -
all offline (mocked HTTP, fixture data)."""

import dataclasses
from datetime import date, timedelta

import httpx
import pytest

from app.infra.http_client import PoliteHttpClient
from app.models import DailyPrice, PriceFile, ResearchQueueItem
from app.repos.screening_repo import ScreeningRepo
from app.schemas.market_data import CompanyProfile, DataQualityReport
from app.services.data.price_sync import sync_prices
from app.services.data.providers.exchange_prices_provider import ExchangePricesProvider
from app.services.data.providers.nse_universe_provider import ExchangeUniverseProvider
from app.services.discovery.company_evaluator import PreparedCompany
from app.services.discovery.event_discovery import EventFeedUnavailable, run_event_discovery
from app.services.discovery.screening_service import run_screening
from app.services.discovery.sector_trends import compute_industry_trends
from tests.conftest import AS_OF
from tests.unit.test_exchange_sources import UDIFF_HEADER, udiff_row, zipped

TRADING_DAY = date(2026, 10, 23)  # Friday


def http(handler) -> PoliteHttpClient:
    def wrapped(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return handler(request)

    return PoliteHttpClient("test-agent", min_interval_seconds=0, client=httpx.Client(transport=httpx.MockTransport(wrapped)),
                            sleep=lambda s: None)  # fmt: skip


def nse_file(sym_prices: dict[str, tuple[float, float]]) -> bytes:
    rows = [udiff_row(i, f"INE{i:03d}", s, "EQ", s, c, v, c * v) for i, (s, (c, v)) in enumerate(sym_prices.items())]
    return zipped("\n".join([UDIFF_HEADER, *rows]))


def test_price_sync_is_incremental_and_records_holidays(session, session_factory):
    holiday = TRADING_DAY - timedelta(days=1)
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if holiday.strftime("%Y%m%d") in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, content=nse_file({"ABC": (100.0, 200_000), "XYZ": (10.0, 100)}))

    out = sync_prices(session, http(handler), ["NSE"], days=7, end=TRADING_DAY)
    # window Fri 16 .. Fri 23 Oct = 6 weekdays (weekends skipped without a request), one of them a holiday
    assert out.loaded["NSE"] == 5 and out.missing["NSE"] == 1
    assert session.query(PriceFile).count() == 6 and session.query(DailyPrice).count() == 10
    n = len(requested)
    sync_prices(session, http(handler), ["NSE"], days=7, end=TRADING_DAY)
    assert len(requested) == n  # nothing re-downloaded

    provider = ExchangePricesProvider(session_factory)
    hist = provider.get_price_history("ABC", TRADING_DAY - timedelta(days=30), TRADING_DAY)
    assert hist.bars[-1].date == TRADING_DAY and hist.bars[-1].close == 100.0
    liq = provider.liquidity_snapshot(TRADING_DAY)
    assert liq["ABC"] == pytest.approx(2.0)  # 100 * 200,000 / 1e7 crore
    assert liq["XYZ"] < 0.01


def test_html_page_instead_of_file_counts_as_unpublished(session):
    out = sync_prices(session, http(lambda r: httpx.Response(200, text="<html>Page not found</html>")), ["NSE"],
                      days=1, end=TRADING_DAY)  # fmt: skip
    assert out.loaded == {} and out.missing["NSE"] == 2 and session.query(DailyPrice).count() == 0  # Thu + Fri


def test_access_refused_stops_exchange(session):
    out = sync_prices(session, http(lambda r: httpx.Response(403)), ["NSE"], days=5, end=TRADING_DAY)
    assert out.loaded == {} and len(out.errors) == 1 and "refused" in out.errors[0]


def test_universe_merges_bse_only_by_isin(monkeypatch):
    nse_csv = (b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
               b"ESDS,ESDS Software Solution Limited,EQ,04-SEP-2026,1,1,INE0DRI01029,1\n")  # fmt: skip
    bse = "\n".join([UDIFF_HEADER, udiff_row(544898, "INE0DRI01029", "ESDS", "B", "ESDS SOFTWARE", "1231", "1", "1"),
                     udiff_row(500001, "INE0BSE00001", "ONLYBSE", "X", "ONLY BSE LIMITED", "10", "1", "1")]).encode()  # fmt: skip

    def handler(request):
        return httpx.Response(200, content=nse_csv if "EQUITY_L" in request.url.path else bse)

    p = ExchangeUniverseProvider(http(handler), "https://archives.nseindia.com/content/equities/EQUITY_L.csv")
    entries, version = p.load_universe()
    by = {e.symbol: e for e in entries}
    assert by["ESDS"].exchange == "NSE" and by["ESDS"].bse_code == "544898"  # dual-listed: one record
    assert by["ONLYBSE"].exchange == "BSE" and by["ONLYBSE"].bse_code == "500001" and by["ONLYBSE"].name == "Only Bse Limited"
    assert "+bse-" in version


def test_liquidity_prefilter_skips_fetching(session, providers, cfg):
    class Liquidity:
        name = "liq"

        def __init__(self, inner):
            self.inner = inner

        def get_price_history(self, *a):
            return self.inner.get_price_history(*a)

        def liquidity_snapshot(self, as_of):
            return {"SMPLALPHA": 5.0, "SMPLBETA": 3.0, "SMPLGAMMA": 0.2}  # everyone else: no trades

    fetched = []
    original = providers.fundamentals.get_financials

    def spy(symbol):
        fetched.append(symbol)
        return original(symbol)

    monkeypatch_fund = dataclasses.replace(providers, market_data=Liquidity(providers.market_data))
    object.__setattr__(monkeypatch_fund.fundamentals, "get_financials", spy)
    run = run_screening(session, monkeypatch_fund, cfg, AS_OF, enqueue_top_n=0)
    assert sorted(set(fetched)) == ["SMPLALPHA", "SMPLBETA"]
    assert run.summary["liquidity_prefiltered"] == 10
    statuses = {c.symbol: (r.status, r.exclusion_reasons) for r, c in ScreeningRepo(session).results_for_run(run.id)}
    assert statuses["SMPLGAMMA"][0] == "rejected" and "pre-filter" in statuses["SMPLGAMMA"][1][0]


def test_event_discovery_screens_only_companies_with_events(session, providers, cfg):
    run_screening(session, providers, cfg, AS_OF, enqueue_top_n=0)  # gives sector medians
    ev_cfg = cfg.model_copy(update={"discovery": cfg.discovery.model_copy(update={"event_categories": ["board_meeting"]})})
    run = run_event_discovery(session, providers, ev_cfg, AS_OF, lookback_days=10)
    rows = ScreeningRepo(session).results_for_run(run.id)
    assert run.kind == "events" and [c.symbol for _, c in rows] == ["SMPLALPHA"]
    result = rows[0][0]
    assert result.status == "candidate" and result.rank == 1
    assert "board_meeting" in result.dimension_scores["trigger_events"][0]
    assert session.query(ResearchQueueItem).filter_by(run_id=run.id).count() == 1
    # universe screening's peer context isn't overwritten by event runs
    assert ScreeningRepo(session).latest_completed_run().kind == "universe"


def test_event_discovery_needs_market_feed(session, providers, cfg):
    class NoFeed:
        name = "nofeed"

    with pytest.raises(EventFeedUnavailable):
        run_event_discovery(session, dataclasses.replace(providers, announcements=NoFeed()), cfg, AS_OF)


def _prepared(industry, q_now, q_prev):
    from app.schemas.market_data import CompanyData
    from app.schemas.screening import Metric

    metrics = {"profit_growth_q_yoy": Metric(key="p", value=q_now, unit="ratio"),
               "profit_growth_q_yoy_prev": Metric(key="pp", value=q_prev, unit="ratio"),
               "revenue_growth_q_yoy": Metric(key="r", value=0.1, unit="ratio")}  # fmt: skip
    data = CompanyData(symbol="S", profile=CompanyProfile(symbol="S", industry=industry))
    dq = DataQualityReport(is_eligible=True, score=100, years_available=5)
    return PreparedCompany("S", "Sector", "non_financial", data, dq, metrics)


def test_industry_trends():
    prepared = ([_prepared("Cement", 0.30, 0.10), _prepared("Cement", 0.20, 0.05), _prepared("Cement", -0.05, 0.0)]
                + [_prepared("Textiles", -0.2, 0.1)] * 3 + [_prepared("Tiny", 0.5, 0.1)] * 2)  # fmt: skip
    trends = compute_industry_trends(prepared, min_companies=3)
    assert set(trends) == {"Cement", "Textiles"}  # "Tiny" has too few companies
    assert trends["Cement"]["improving"] and trends["Cement"]["breadth"] == pytest.approx(2 / 3, abs=1e-3)
    assert not trends["Textiles"]["improving"]
    assert list(trends) == ["Cement", "Textiles"]  # best first
