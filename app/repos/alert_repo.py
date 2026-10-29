from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, Company


class AlertRepo:
    def __init__(self, session: Session):
        self.s = session

    def exists(self, deduplication_key: str) -> bool:
        return self.s.scalar(select(Alert.id).where(Alert.deduplication_key == deduplication_key)) is not None

    def last_triggered_at(self, company_id: int, rule_id: str) -> datetime | None:
        return self.s.scalar(
            select(Alert.triggered_at)
            .where(Alert.company_id == company_id, Alert.rule_id == rule_id)
            .order_by(Alert.triggered_at.desc())
            .limit(1)
        )

    def add(self, alert: Alert) -> Alert:
        self.s.add(alert)
        self.s.flush()
        return alert

    def undelivered(self, max_attempts: int) -> list[Alert]:
        return list(
            self.s.scalars(
                select(Alert)
                .where(Alert.delivery_status.in_(("pending", "failed")), Alert.attempts < max_attempts)
                .order_by(Alert.id)
            )
        )

    def search(
        self, symbol: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[tuple[Alert, Company]]:
        q = select(Alert, Company).join(Company, Company.id == Alert.company_id).order_by(Alert.id.desc()).limit(limit)
        if symbol:
            q = q.where(Company.symbol == symbol)
        if status:
            q = q.where(Alert.delivery_status == status)
        return [(a, c) for a, c in self.s.execute(q).all()]
