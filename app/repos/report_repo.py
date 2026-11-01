from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, ResearchReport


class ReportRepo:
    def __init__(self, session: Session):
        self.s = session

    def add(self, report: ResearchReport) -> ResearchReport:
        self.s.add(report)
        self.s.flush()
        return report

    def get(self, report_id: int) -> tuple[ResearchReport, Company] | None:
        row = self.s.execute(
            select(ResearchReport, Company).join(Company).where(ResearchReport.id == report_id)
        ).first()
        return (row[0], row[1]) if row else None

    def search(self, symbol: str | None = None, limit: int = 50) -> list[tuple[ResearchReport, Company]]:
        q = select(ResearchReport, Company).join(Company).order_by(ResearchReport.id.desc()).limit(limit)
        if symbol:
            q = q.where(Company.symbol == symbol)
        return [(r, c) for r, c in self.s.execute(q).all()]

    def latest_for_company(self, company_id: int) -> ResearchReport | None:
        return self.s.scalar(
            select(ResearchReport)
            .where(ResearchReport.company_id == company_id)
            .order_by(ResearchReport.id.desc())
            .limit(1)
        )

    def latest_per_company(self) -> list[tuple[ResearchReport, Company]]:
        """Each company's most recent report."""
        latest = select(func.max(ResearchReport.id)).group_by(ResearchReport.company_id).scalar_subquery()
        q = select(ResearchReport, Company).join(Company).where(ResearchReport.id.in_(latest))
        return [(r, c) for r, c in self.s.execute(q).all()]
