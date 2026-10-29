from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialSnapshot, MarketSnapshot, Source
from app.schemas.market_data import FinancialValue, PriceBar, SourceRef


class SnapshotRepo:
    def __init__(self, session: Session):
        self.s = session

    def get_or_create_source(self, company_id: int | None, ref: SourceRef, content_hash: str) -> Source:
        src = self.s.scalar(select(Source).where(Source.provider == ref.provider, Source.content_hash == content_hash))
        if src:
            return src
        src = Source(
            company_id=company_id,
            provider=ref.provider,
            source_type=ref.source_type,
            url=ref.url,
            title=ref.title,
            document_id=ref.document_id,
            published_at=ref.published_at,
            retrieved_at=ref.retrieved_at,
            content_hash=content_hash,
            is_synthetic=ref.is_synthetic,
            extra={"key": ref.key},
        )
        self.s.add(src)
        self.s.flush()
        return src

    def add_financials(self, company_id: int, values: list[FinancialValue], source_ids: dict[str, int]) -> int:
        existing = set(
            self.s.execute(
                select(
                    FinancialSnapshot.period, FinancialSnapshot.period_type, FinancialSnapshot.metric,
                    FinancialSnapshot.consolidation_type, FinancialSnapshot.source_id,
                ).where(FinancialSnapshot.company_id == company_id)
            ).all()
        )  # fmt: skip
        added = 0
        for v in values:
            sid = source_ids[v.source_key]
            key = (v.period, v.period_type.value, v.metric, v.consolidation.value, sid)
            if key in existing:
                continue
            self.s.add(
                FinancialSnapshot(
                    company_id=company_id, period=v.period, period_end=v.period_end, period_type=v.period_type.value,
                    metric=v.metric, value=v.value, unit=v.unit, consolidation_type=v.consolidation.value, source_id=sid,
                )
            )  # fmt: skip
            existing.add(key)
            added += 1
        return added

    def add_market_bars(self, company_id: int, bars: list[PriceBar], source_id: int) -> int:
        existing = set(
            self.s.scalars(
                select(MarketSnapshot.timestamp).where(
                    MarketSnapshot.company_id == company_id, MarketSnapshot.source_id == source_id
                )
            )
        )
        new = [b for b in bars if b.date not in existing]
        self.s.add_all(
            MarketSnapshot(company_id=company_id, timestamp=b.date, price=b.close, volume=b.volume, source_id=source_id)
            for b in new
        )
        return len(new)
