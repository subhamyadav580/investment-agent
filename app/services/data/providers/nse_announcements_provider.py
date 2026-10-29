"""NSE corporate announcements, board meetings (results dates), and promoter pledge data.

Uses NSE's public JSON endpoints with an honest User-Agent via PoliteHttpClient. If NSE refuses access, calls
fail with ProviderError and the data is reported as unavailable - the client never tries to get around it.
BSE-only companies (addressed by numeric scrip code) have no announcements here.
"""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.infra.http_client import FetchError, PoliteHttpClient
from app.schemas.market_data import Announcement, Shareholding, SourceRef
from app.services.data.announcement_classifier import classify_announcement
from app.services.data.providers.base import ProviderError

IST = ZoneInfo("Asia/Kolkata")
API = "https://www.nseindia.com/api"
CACHE_SECONDS = 6 * 3600


def _dt(value: str | None) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime((value or "").strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _num(value) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_announcements(rows: list[dict], retrieved_at: datetime) -> list[Announcement]:
    out = []
    for r in rows:
        published = _dt(r.get("an_dt")) or _dt(r.get("dt"))
        symbol = (r.get("symbol") or "").strip()
        if not published or not symbol:
            continue
        subject, text = r.get("desc") or "", r.get("attchmntText") or ""
        ann_id = f"nse:{r.get('seq_id') or f'{symbol}:{published.isoformat()}'}"
        out.append(Announcement(
            id=ann_id, symbol=symbol, category=classify_announcement(subject, text), title=f"{symbol}: {subject}".strip(),
            published_at=published, summary=text[:2000] or None,
            source=SourceRef(key=f"{symbol}:announcement:{ann_id}", provider="nse", source_type="exchange_filing",
                             url=r.get("attchmntFile"), title=subject or "NSE announcement", published_at=published,
                             retrieved_at=retrieved_at),
        ))  # fmt: skip
    return out


def parse_board_meetings(rows: list[dict], retrieved_at: datetime) -> list[Announcement]:
    out = []
    for r in rows:
        symbol = (r.get("bm_symbol") or "").strip()
        meeting = _dt(r.get("bm_date"))
        published = _dt(r.get("bm_timestamp")) or meeting
        if not symbol or not meeting:
            continue
        purpose = r.get("bm_purpose") or "Board meeting"
        ann_id = f"nse:bm:{symbol}:{meeting.date()}:{purpose}"
        out.append(Announcement(
            id=ann_id, symbol=symbol,
            category="board_meeting", title=f"{symbol}: board meeting on {meeting.date()} ({purpose})",
            published_at=published, event_date=meeting.date(), summary=(r.get("bm_desc") or "")[:2000] or None,
            source=SourceRef(key=f"{symbol}:announcement:{ann_id}", provider="nse", source_type="exchange_filing",
                             url=r.get("attachment") or None, title=f"Board meeting intimation: {purpose}",
                             published_at=published, retrieved_at=retrieved_at),
        ))  # fmt: skip
    return out


def parse_pledge(payload: dict, symbol: str, retrieved_at: datetime) -> Shareholding | None:
    rows = payload.get("data") or []
    if not rows:
        return None
    r = rows[0]  # latest disclosure first
    period = _dt(r.get("shp"))
    if not period:
        return None
    return Shareholding(
        period_end=period.date(),
        promoter_holding_pct=_num(r.get("percPromoterHolding")),
        promoter_pledged_pct=_num(r.get("percPromoterShares")),  # % of promoter holding that is pledged
        source=SourceRef(key=f"{symbol}:pledge:{period.date()}", provider="nse", source_type="exchange_filing",
                         url=f"{API}/corporate-pledgedata?index=equities&symbol={symbol}",
                         title=f"Promoter pledge disclosure {period.date()}", retrieved_at=retrieved_at),
    )  # fmt: skip


class NseAnnouncementsProvider:
    name = "nse"

    def __init__(self, client: PoliteHttpClient):
        self.client = client

    def _json(self, path: str, params: dict):
        try:
            res = self.client.get(f"{API}/{path}", params=params, ttl_seconds=CACHE_SECONDS)
        except FetchError as e:
            raise ProviderError(f"NSE {path}: {e}") from e
        try:
            return json.loads(res.content), res.fetched_at
        except json.JSONDecodeError as e:
            raise ProviderError(f"NSE {path}: response was not JSON") from e

    def get_announcements(self, symbol: str, since: date) -> list[Announcement]:
        if symbol.isdigit():
            return []  # BSE-only company
        until = date.today()
        rows, at = self._json("corporate-announcements", {"index": "equities", "symbol": symbol,
                                                          "from_date": f"{since:%d-%m-%Y}", "to_date": f"{until:%d-%m-%Y}"})  # fmt: skip
        anns = parse_announcements(rows if isinstance(rows, list) else [], at)
        bm_rows, at = self._json("corporate-board-meetings", {"index": "equities", "symbol": symbol})
        anns += [a for a in parse_board_meetings(bm_rows if isinstance(bm_rows, list) else [], at)
                 if a.published_at.date() >= since]  # fmt: skip
        return anns

    def get_pledge(self, symbol: str) -> Shareholding | None:
        if symbol.isdigit():
            return None
        payload, at = self._json("corporate-pledgedata", {"index": "equities", "symbol": symbol})
        return parse_pledge(payload if isinstance(payload, dict) else {}, symbol, at)

    def market_announcements(self, start: date, end: date) -> list[Announcement]:
        """All NSE announcements in a date range (for event-driven discovery). Fetched one day at a time."""
        out: list[Announcement] = []
        d = start
        while d <= end:
            rows, at = self._json("corporate-announcements", {"index": "equities", "from_date": f"{d:%d-%m-%Y}",
                                                              "to_date": f"{d:%d-%m-%Y}"})  # fmt: skip
            out += parse_announcements(rows if isinstance(rows, list) else [], at)
            d += timedelta(days=1)
        return out
