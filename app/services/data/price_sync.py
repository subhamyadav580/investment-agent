"""Downloads exchange price files for missing trading days and stores whole-market closes in daily_prices."""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infra.http_client import AccessDenied, FetchError, NotFound, PoliteHttpClient
from app.models import DailyPrice
from app.repos.price_repo import PriceRepo
from app.services.data.providers.bhavcopy import bse_url, dedupe, nse_url, parse_bse, parse_nse

logger = logging.getLogger(__name__)

SOURCES = {"NSE": (nse_url, parse_nse), "BSE": (bse_url, parse_bse)}


@dataclass
class SyncResult:
    loaded: dict[str, int] = field(default_factory=dict)  # exchange -> files loaded
    missing: dict[str, int] = field(default_factory=dict)  # holidays / not published
    errors: list[str] = field(default_factory=list)


def sync_prices(
    session: Session, client: PoliteHttpClient, exchanges: list[str], days: int, end: date
) -> SyncResult:
    repo = PriceRepo(session)
    start = end - timedelta(days=days)
    out = SyncResult()
    for exchange in exchanges:
        url_for, parse = SOURCES[exchange]
        done = repo.processed_dates(exchange, start, end)
        d = end
        while d >= start:
            # Weekends never have files; skip without a request. Unpublished/holiday days are recorded as missing.
            if d.weekday() < 5 and d not in done and (url := url_for(d)):
                try:
                    rows = dedupe(parse(client.get(url).content))
                    if not rows:  # some sites answer 200 with an HTML page for files that don't exist yet
                        raise NotFound(url)
                except NotFound:
                    if d < end:  # today's file may simply not be out yet: retry next time
                        repo.record_file(exchange, d, "missing", 0, url)
                    out.missing[exchange] = out.missing.get(exchange, 0) + 1
                except AccessDenied as e:
                    out.errors.append(str(e))
                    logger.warning("price file access refused; stopping this exchange", extra={"exchange": exchange})
                    break
                except FetchError as e:
                    out.errors.append(str(e))
                else:
                    repo.add_prices([
                        DailyPrice(exchange=exchange, security_key=r.security_key, isin=r.isin, series=r.series,
                                   trade_date=d, close=r.close, volume=r.volume, traded_value=r.traded_value)
                        for r in rows
                    ])  # fmt: skip
                    repo.record_file(exchange, d, "loaded", len(rows), url)
                    out.loaded[exchange] = out.loaded.get(exchange, 0) + 1
                try:
                    session.commit()
                except IntegrityError as e:  # one bad file must not stop the sync
                    session.rollback()
                    out.loaded[exchange] = out.loaded.get(exchange, 1) - 1
                    out.errors.append(f"{exchange} {d}: could not store ({type(e.orig).__name__})")
            d -= timedelta(days=1)
        logger.info("price sync done", extra={"exchange": exchange, "loaded": out.loaded.get(exchange, 0)})
    return out
