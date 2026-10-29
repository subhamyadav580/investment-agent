from datetime import date

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.dependencies import get_data_providers, get_db, get_llm, get_notifier, get_screening_config
from app.models import Company, ResearchReport
from app.repos.company_repo import CompanyRepo
from app.repos.report_repo import ReportRepo
from app.schemas.research import QueueProcessOut, ResearchReportOut, ResearchReportSummaryOut, ResearchRequest
from app.services.alerts.notifier import Notifier
from app.services.data.normalization import normalize_symbol
from app.services.data.providers.registry import Providers
from app.services.discovery.candidate_queue import enqueue_one
from app.services.discovery.rules_config import ScreeningConfig
from app.services.graph.deps import GraphDeps
from app.services.graph.llm import StructuredLLM
from app.services.research.research_service import ResearchError, ResearchService


def _service(db, providers, cfg, llm, notifier, settings: Settings) -> ResearchService:
    deps = GraphDeps(
        session=db, providers=providers, cfg=cfg, llm=llm, prompt_version=settings.prompt_version,
        quiet_hours=settings.alert_quiet_period_hours, report_base_url=settings.report_base_url,
    )  # fmt: skip
    return ResearchService(deps, notifier, settings.alert_max_delivery_attempts)


def _report_out(r: ResearchReport, c: Company) -> ResearchReportOut:
    return ResearchReportOut(
        id=r.id, symbol=c.symbol, as_of_date=r.as_of_date, status=r.status, conclusion=r.conclusion,
        model_version=r.model_version, prompt_version=r.prompt_version, rules_version=r.rules_version,
        created_at=r.created_at, report=r.report_json,
    )  # fmt: skip


def run_research(
    body: ResearchRequest,
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_data_providers),
    cfg: ScreeningConfig = Depends(get_screening_config),
    llm: StructuredLLM = Depends(get_llm),
    notifier: Notifier = Depends(get_notifier),
    settings: Settings = Depends(get_settings),
) -> ResearchReportOut:
    service = _service(db, providers, cfg, llm, notifier, settings)
    try:
        outcome = service.research(body.query, body.as_of_date or date.today())
    except ResearchError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return _report_out(*ReportRepo(db).get(outcome.report_id))


def enqueue_research(symbol: str, db: Session = Depends(get_db)) -> dict:
    company = CompanyRepo(db).get_by_symbol(normalize_symbol(symbol))
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{symbol} not in the company universe; run screening first")
    return {"symbol": company.symbol, "enqueued": enqueue_one(db, company.id)}


def process_queue(
    limit: int | None = None,
    as_of_date: date | None = None,
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_data_providers),
    cfg: ScreeningConfig = Depends(get_screening_config),
    llm: StructuredLLM = Depends(get_llm),
    notifier: Notifier = Depends(get_notifier),
    settings: Settings = Depends(get_settings),
) -> QueueProcessOut:
    service = _service(db, providers, cfg, llm, notifier, settings)
    return service.process_queue(
        limit or settings.research_batch_size, settings.research_max_attempts, as_of_date or date.today()
    )


def list_reports(
    symbol: str | None = None, limit: int = 50, db: Session = Depends(get_db)
) -> list[ResearchReportSummaryOut]:
    return [
        ResearchReportSummaryOut(id=r.id, symbol=c.symbol, as_of_date=r.as_of_date, status=r.status,
                                 conclusion=r.conclusion, created_at=r.created_at)  # fmt: skip
        for r, c in ReportRepo(db).search(normalize_symbol(symbol) if symbol else None, limit)
    ]


def get_report(report_id: int, db: Session = Depends(get_db)) -> ResearchReportOut:
    row = ReportRepo(db).get(report_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"report {report_id} not found")
    return _report_out(*row)
