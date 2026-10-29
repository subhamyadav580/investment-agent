from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DailyPrice, PriceFile


class PriceRepo:
    def __init__(self, session: Session):
        self.s = session

    def processed_dates(self, exchange: str, start: date, end: date) -> set[date]:
        return set(
            self.s.scalars(
                select(PriceFile.trade_date).where(
                    PriceFile.exchange == exchange, PriceFile.trade_date >= start, PriceFile.trade_date <= end
                )
            )
        )

    def record_file(self, exchange: str, trade_date: date, status: str, rows: int, url: str) -> None:
        self.s.add(PriceFile(exchange=exchange, trade_date=trade_date, status=status, rows=rows, url=url))

    def add_prices(self, rows: list[DailyPrice]) -> None:
        self.s.add_all(rows)

    def history(self, exchange: str, security_key: str, start: date, end: date) -> list[DailyPrice]:
        return list(
            self.s.scalars(
                select(DailyPrice)
                .where(
                    DailyPrice.exchange == exchange,
                    DailyPrice.security_key == security_key,
                    DailyPrice.trade_date >= start,
                    DailyPrice.trade_date <= end,
                )
                .order_by(DailyPrice.trade_date)
            )
        )

    def avg_traded_value(self, exchange: str, start: date, end: date) -> dict[str, float]:
        """security_key -> average daily traded value (INR) over [start, end]."""
        rows = self.s.execute(
            select(DailyPrice.security_key, func.avg(DailyPrice.traded_value))
            .where(DailyPrice.exchange == exchange, DailyPrice.trade_date >= start, DailyPrice.trade_date <= end)
            .group_by(DailyPrice.security_key)
        ).all()
        return {k: float(v) for k, v in rows if v is not None}

    def latest_date(self, exchange: str) -> date | None:
        return self.s.scalar(select(func.max(DailyPrice.trade_date)).where(DailyPrice.exchange == exchange))
