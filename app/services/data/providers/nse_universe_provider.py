"""NSE listed-equity universe from the exchange's public EQUITY_L.csv securities list.

Downloaded at most once per run (it changes slowly). If you prefer not to fetch from NSE at all, download the
file manually and point NSE_EQUITY_LIST_PATH at it. Check NSE's website terms before automating access.
"""

import hashlib
import io
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pandas as pd

from app.infra.http_client import FetchError, NotFound
from app.schemas.market_data import UniverseEntry
from app.services.data.normalization import normalize_symbol
from app.services.data.providers.base import ProviderError
from app.services.data.providers.bhavcopy import BSE_SME_GROUPS, bse_url, parse_bse

if TYPE_CHECKING:
    from app.infra.http_client import PoliteHttpClient
    from app.services.data.providers.bhavcopy import PriceRow

logger = logging.getLogger(__name__)

# NSE series codes for main-board equity. SM/ST are SME platform series.
MAIN_BOARD_SERIES = {"EQ", "BE", "BZ", "BL"}
SME_SERIES = {"SM", "ST", "SZ"}
_NON_EQUITY_NAME_HINTS = (" ETF", "EXCHANGE TRADED", " REIT", " INVIT", "INFRASTRUCTURE INVESTMENT TRUST")


class NseCsvUniverseProvider:
    name = "nse_csv"

    def __init__(self, url: str, local_path: Path | None = None, timeout: float = 20.0):
        self.url = url
        self.local_path = local_path
        self.timeout = timeout

    def _read_bytes(self) -> bytes:
        if self.local_path:
            return self.local_path.read_bytes()
        headers = {"User-Agent": "Mozilla/5.0 (personal research tool)", "Accept": "text/csv"}
        try:
            resp = httpx.get(self.url, headers=headers, timeout=self.timeout, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"NSE equity list download failed: {e}") from e
        return resp.content

    def load_universe(self) -> tuple[list[UniverseEntry], str]:
        raw = self._read_bytes()
        version = "nse-" + hashlib.sha256(raw).hexdigest()[:12]
        return parse_equity_list(raw), version


def parse_equity_list(raw: bytes) -> list[UniverseEntry]:
    df = pd.read_csv(io.BytesIO(raw), dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]
    required = {"SYMBOL", "NAME OF COMPANY", "SERIES"}
    if missing := required - set(df.columns):
        raise ProviderError(f"NSE equity list missing columns: {sorted(missing)}")

    entries = []
    for row in df.to_dict("records"):
        symbol = normalize_symbol(str(row["SYMBOL"]))
        name = str(row["NAME OF COMPANY"]).strip()
        series = str(row.get("SERIES") or "").strip().upper()
        upper_name = f" {name.upper()}"
        if any(h in upper_name for h in _NON_EQUITY_NAME_HINTS):
            instrument = "ETF" if "ETF" in upper_name or "EXCHANGE TRADED" in upper_name else "TRUST"
        elif series in MAIN_BOARD_SERIES or series in SME_SERIES:
            instrument = "EQUITY"
        else:
            instrument = "OTHER"
        entries.append(
            UniverseEntry(
                symbol=symbol,
                name=name,
                exchange="NSE",
                isin=(str(row.get("ISIN NUMBER") or "").strip() or None),
                series=series or None,
                instrument_type=instrument,
                is_sme=series in SME_SERIES,
                listed_on=_parse_listing_date(row.get("DATE OF LISTING")),
            )
        )
    logger.info("parsed NSE equity list", extra={"rows": len(entries)})
    return entries


def _parse_listing_date(value: object) -> date | None:
    if not value or (isinstance(value, float) and pd.isna(value)):
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


class ExchangeUniverseProvider:
    """NSE main-board list plus companies listed only on BSE (taken from BSE's latest daily price file),
    de-duplicated by ISIN. Companies on both exchanges appear once, as NSE, with their BSE code attached."""

    name = "nse_bse"

    def __init__(self, client: "PoliteHttpClient", nse_url: str, include_bse_only: bool = True):
        self.client = client
        self.nse_url = nse_url
        self.include_bse_only = include_bse_only

    def _latest_bse_rows(self, today: date) -> tuple[list["PriceRow"], date] | tuple[list, None]:
        d = today
        for _ in range(10):  # walk back over weekends/holidays to the latest published file
            if d.weekday() < 5 and (url := bse_url(d)):
                try:
                    rows = parse_bse(self.client.get(url, ttl_seconds=12 * 3600).content)
                except NotFound:
                    rows = []
                if rows:  # BSE answers 200 with a web page for unpublished days: no rows = not published
                    return rows, d
            d -= timedelta(days=1)
        return [], None

    def load_universe(self) -> tuple[list[UniverseEntry], str]:
        try:
            nse_raw = self.client.get(self.nse_url, ttl_seconds=12 * 3600).content
        except FetchError as e:
            raise ProviderError(f"NSE equity list download failed: {e}") from e
        nse = parse_equity_list(nse_raw)
        version = "nse-" + hashlib.sha256(nse_raw).hexdigest()[:10]
        if not self.include_bse_only:
            return nse, version

        try:
            bse_rows, bse_date = self._latest_bse_rows(date.today())
        except FetchError as e:
            logger.warning("BSE list unavailable; continuing with NSE only", extra={"error": str(e)})
            return nse, version
        by_isin = {e.isin: e for e in nse if e.isin}
        bse_only = []
        for r in bse_rows:
            if r.isin and r.isin in by_isin:
                by_isin[r.isin].bse_code = r.security_key
                continue
            bse_only.append(UniverseEntry(
                symbol=r.symbol or r.security_key, name=(r.name or r.symbol).title(), exchange="BSE", isin=r.isin,
                bse_code=r.security_key, series=r.series, instrument_type="EQUITY",
                is_sme=r.series in BSE_SME_GROUPS,
            ))  # fmt: skip
        logger.info("universe merged", extra={"nse": len(nse), "bse_only": len(bse_only), "bse_file": str(bse_date)})
        return nse + bse_only, f"{version}+bse-{bse_date}"
