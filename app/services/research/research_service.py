"""Runs the research graph for on-demand queries and for the screening candidate queue."""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.repos.company_repo import CompanyRepo
from app.repos.screening_repo import ResearchQueueRepo
from app.schemas.research import QueueProcessOut
from app.services.alerts.alert_service import deliver_pending
from app.services.alerts.notifier import Notifier
from app.services.graph.builder import build_research_graph
from app.services.graph.deps import GraphDeps

logger = logging.getLogger(__name__)


class ResearchError(Exception):
    pass


@dataclass
class ResearchOutcome:
    report_id: int
    symbol: str
    conclusion: str
    alerts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ResearchService:
    def __init__(self, deps: GraphDeps, notifier: Notifier | None = None, max_delivery_attempts: int = 5):
        self.deps = deps
        self.session: Session = deps.session
        self.notifier = notifier
        self.max_delivery_attempts = max_delivery_attempts
        self.graph = build_research_graph(deps)

    def research(self, query: str, as_of: date) -> ResearchOutcome:
        final = self.graph.invoke({"query": query, "as_of_date": as_of.isoformat(), "errors": [], "llm_calls": []})
        if not final.get("report_id"):
            self.session.rollback()
            raise ResearchError("; ".join(final.get("errors") or ["research produced no report"]))
        self.session.commit()
        if final.get("alerts") and self.notifier:
            deliver_pending(self.session, self.notifier, self.max_delivery_attempts)
            self.session.commit()
        return ResearchOutcome(
            report_id=final["report_id"],
            symbol=final["symbol"],
            conclusion=final["report"]["conclusion"],
            alerts=final.get("alerts", []),
            errors=final.get("errors", []),
        )

    def process_queue(self, limit: int, max_attempts: int, as_of: date) -> QueueProcessOut:
        repo = ResearchQueueRepo(self.session)
        items = repo.claim(limit, max_attempts)
        self.session.commit()
        companies = CompanyRepo(self.session).list_by_ids([i.company_id for i in items])
        out = QueueProcessOut(processed=len(items), succeeded=0, failed=0, report_ids=[])
        for item in items:
            symbol = companies[item.company_id].symbol
            try:
                outcome = self.research(symbol, as_of)
            except Exception as e:
                self.session.rollback()
                item = self.session.merge(item)
                repo.finish(item, error=f"{type(e).__name__}: {e}"[:2000])
                out.failed += 1
                logger.warning("queued research failed", extra={"symbol": symbol, "error": str(e)[:300]})
            else:
                repo.finish(item, report_id=outcome.report_id)
                out.succeeded += 1
                out.report_ids.append(outcome.report_id)
            self.session.commit()
        return out
