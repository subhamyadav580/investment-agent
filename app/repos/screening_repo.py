from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Company, ResearchQueueItem, ScreeningResult, ScreeningRun


class ScreeningRepo:
    def __init__(self, session: Session):
        self.s = session

    def create_run(
        self, as_of_date: str, universe_version: str, rules_version: str, kind: str = "universe"
    ) -> ScreeningRun:
        run = ScreeningRun(
            as_of_date=as_of_date, universe_version=universe_version, rules_version=rules_version, kind=kind
        )
        self.s.add(run)
        self.s.flush()
        return run

    def get_run(self, run_id: int) -> ScreeningRun | None:
        return self.s.get(ScreeningRun, run_id)

    def list_runs(self, limit: int = 20) -> list[ScreeningRun]:
        return list(self.s.scalars(select(ScreeningRun).order_by(ScreeningRun.id.desc()).limit(limit)))

    def latest_completed_run(self, kind: str = "universe") -> ScreeningRun | None:
        return self.s.scalar(
            select(ScreeningRun)
            .where(ScreeningRun.status == "completed", ScreeningRun.kind == kind)
            .order_by(ScreeningRun.id.desc())
            .limit(1)
        )

    def add_result(self, result: ScreeningResult) -> None:
        self.s.add(result)

    def results_for_run(self, run_id: int, status: str | None = None) -> list[tuple[ScreeningResult, Company]]:
        q = (
            select(ScreeningResult, Company)
            .join(Company, Company.id == ScreeningResult.company_id)
            .where(ScreeningResult.run_id == run_id)
        )
        if status:
            q = q.where(ScreeningResult.status == status)
        q = q.order_by(ScreeningResult.rank.is_(None), ScreeningResult.rank, ScreeningResult.score.desc())
        return [(r, c) for r, c in self.s.execute(q).all()]

    def result_for_company(self, run_id: int, company_id: int) -> ScreeningResult | None:
        return self.s.scalar(
            select(ScreeningResult).where(ScreeningResult.run_id == run_id, ScreeningResult.company_id == company_id)
        )


class ResearchQueueRepo:
    def __init__(self, session: Session):
        self.s = session

    def has_open_item(self, company_id: int) -> bool:
        return (
            self.s.scalar(
                select(ResearchQueueItem.id).where(
                    ResearchQueueItem.company_id == company_id, ResearchQueueItem.status.in_(("pending", "running"))
                )
            )
            is not None
        )

    def add(self, company_id: int, run_id: int | None, priority: float) -> ResearchQueueItem:
        item = ResearchQueueItem(company_id=company_id, run_id=run_id, priority=priority)
        self.s.add(item)
        self.s.flush()
        return item

    def claim(self, limit: int, max_attempts: int) -> list[ResearchQueueItem]:
        q = (
            select(ResearchQueueItem)
            .where(ResearchQueueItem.status.in_(("pending", "failed")), ResearchQueueItem.attempts < max_attempts)
            .order_by(ResearchQueueItem.priority.desc(), ResearchQueueItem.id)
            .limit(limit)
        )
        if self.s.bind.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        items = list(self.s.scalars(q))
        now = utcnow()
        for item in items:
            item.status, item.started_at = "running", now
            item.attempts += 1
        self.s.flush()
        return items

    def finish(self, item: ResearchQueueItem, *, report_id: int | None = None, error: str | None = None) -> None:
        item.status = "failed" if error else "done"
        item.last_error = error
        item.report_id = report_id
        item.finished_at = utcnow()

    def list_items(self, status: str | None = None, limit: int = 100) -> list[ResearchQueueItem]:
        q = select(ResearchQueueItem).order_by(ResearchQueueItem.id.desc()).limit(limit)
        if status:
            q = q.where(ResearchQueueItem.status == status)
        return list(self.s.scalars(q))
