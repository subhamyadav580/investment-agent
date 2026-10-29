"""Price history from exchange price files already synced into daily_prices (see services/data/price_sync.py).

Reads only from the database: run the price sync (worker job or CLI) to keep it current.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.repos.price_repo import PriceRepo
from app.schemas.market_data import PriceBar, PriceHistory, SourceRef
from app.services.data.providers.base import DataNotAvailable

LIQUIDITY_WINDOW_DAYS = 90  # calendar days, ~60 sessions


class ExchangePricesProvider:
    name = "exchange_bhavcopy"

    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    @staticmethod
    def _exchange_for(symbol: str) -> str:
        return "BSE" if symbol.isdigit() else "NSE"  # BSE-only companies are addressed by scrip code

    def get_price_history(self, symbol: str, start: date, end: date) -> PriceHistory:
        exchange = self._exchange_for(symbol)
        with self.session_factory() as s:
            rows = PriceRepo(s).history(exchange, symbol, start, end)
        if not rows:
            raise DataNotAvailable(f"{symbol}: no {exchange} prices synced for {start}..{end}")
        source = SourceRef(
            key=f"{symbol}:prices",
            provider=self.name,
            source_type="price_feed",
            title=f"{exchange} daily price files (bhavcopy) {rows[0].trade_date}..{rows[-1].trade_date}",
            url="https://www.nseindia.com/all-reports" if exchange == "NSE" else "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx",
            published_at=datetime.combine(rows[-1].trade_date, datetime.min.time(), UTC),
            retrieved_at=datetime.now(UTC),
        )
        bars = [PriceBar(date=r.trade_date, close=r.close, volume=r.volume) for r in rows]
        return PriceHistory(symbol=symbol, bars=bars, source=source)

    def liquidity_snapshot(self, as_of: date) -> dict[str, float]:
        """provider symbol -> average daily traded value in INR crore (for the screening pre-filter).
        Empty if no prices have been synced, which disables the pre-filter."""
        start = as_of - timedelta(days=LIQUIDITY_WINDOW_DAYS)
        out: dict[str, float] = {}
        with self.session_factory() as s:
            repo = PriceRepo(s)
            for exchange in ("NSE", "BSE"):
                for key, value in repo.avg_traded_value(exchange, start, as_of).items():
                    out[key] = max(out.get(key, 0.0), value / 1e7)
        return out
