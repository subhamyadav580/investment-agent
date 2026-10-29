"""Job bodies. Each opens its own session/transaction; failures are logged and never kill the scheduler."""

import logging
from datetime import date

from app.core.config import get_settings
from app.db.session import session_scope
from app.services.alerts.alert_service import deliver_pending, run_monitoring
from app.services.alerts.notifier import build_notifier
from app.services.data.price_sync import sync_prices
from app.services.data.providers.registry import build_http_client, get_providers
from app.services.discovery.event_discovery import EventFeedUnavailable, run_event_discovery
from app.services.discovery.rules_config import load_screening_config
from app.services.discovery.screening_service import run_screening
from app.services.graph.deps import GraphDeps
from app.services.graph.llm_factory import build_llm
from app.services.research.research_service import ResearchService

logger = logging.getLogger(__name__)


def _cfg():
    return load_screening_config(get_settings().screening_rules_path)


def weekly_screening_job() -> None:
    with session_scope() as session:
        run = run_screening(session, get_providers(), _cfg(), date.today())
        logger.info("scheduled screening finished", extra={"run_id": run.id, "summary": run.summary.get("status_counts")})


def daily_monitoring_job() -> None:
    s = get_settings()
    with session_scope() as session:
        out = run_monitoring(
            session, get_providers(), _cfg(), date.today(), build_notifier(s),
            quiet_hours=s.alert_quiet_period_hours, max_attempts=s.alert_max_delivery_attempts,
            report_base_url=s.report_base_url,
        )  # fmt: skip
        logger.info("monitoring finished", extra=out.model_dump())


def research_queue_job() -> None:
    s = get_settings()
    with session_scope() as session:
        deps = GraphDeps(
            session=session, providers=get_providers(), cfg=_cfg(), llm=build_llm(s),
            prompt_version=s.prompt_version, quiet_hours=s.alert_quiet_period_hours, report_base_url=s.report_base_url,
        )  # fmt: skip
        out = ResearchService(deps, build_notifier(s), s.alert_max_delivery_attempts).process_queue(
            s.research_batch_size, s.research_max_attempts, date.today()
        )
        if out.processed:
            logger.info("research queue batch finished", extra=out.model_dump())


def alert_retry_job() -> None:
    s = get_settings()
    with session_scope() as session:
        if n := deliver_pending(session, build_notifier(s), s.alert_max_delivery_attempts):
            logger.info("retried alert deliveries", extra={"delivered": n})


def price_sync_job() -> None:
    s = get_settings()
    if s.market_data_provider != "exchange_bhavcopy":
        return
    with session_scope() as session:
        out = sync_prices(session, build_http_client(s), s.price_sync_exchanges, s.price_backfill_days, date.today())
        logger.info("price sync finished", extra={"loaded": out.loaded, "errors": out.errors[:5]})


def event_discovery_job() -> None:
    with session_scope() as session:
        try:
            run = run_event_discovery(session, get_providers(), _cfg(), date.today())
        except EventFeedUnavailable as e:
            logger.info("event discovery skipped", extra={"reason": str(e)})
            return
        logger.info("event discovery finished", extra={"run_id": run.id, **run.summary.get("status_counts", {})})
