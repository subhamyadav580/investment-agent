"""Alert evaluation, dedup + quiet periods, persistence, delivery with retries, and watchlist monitoring."""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Alert, Company, WatchlistCompany
from app.repos.alert_repo import AlertRepo
from app.repos.report_repo import ReportRepo
from app.repos.screening_repo import ScreeningRepo
from app.repos.watchlist_repo import WatchlistRepo
from app.schemas.alerts import AlertCandidate, MonitoringRunOut
from app.services.alerts.deduplication import deduplication_key, in_quiet_period
from app.services.alerts.notifier import Notifier
from app.services.alerts.rules import AlertContext, evaluate_alert_rules
from app.services.data.identity import provider_symbol
from app.services.data.providers.registry import Providers
from app.services.discovery.company_evaluator import EvaluatedCompany, evaluate, prepare
from app.services.discovery.data_enrichment import apply_profile, fetch_company_data, persist_company_data
from app.services.discovery.rules_config import ScreeningConfig

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7


def record_alerts(
    session: Session,
    company: Company,
    candidates: list[AlertCandidate],
    *,
    quiet_hours: int,
    quiet_exempt: list[str],
    report_url: str | None = None,
    now: datetime | None = None,
) -> list[Alert]:
    repo = AlertRepo(session)
    now = now or utcnow()
    created: list[Alert] = []
    seen: set[str] = set()
    for c in candidates:
        key = deduplication_key(company.id, c.rule_id, c.fingerprint)
        if key in seen or repo.exists(key):
            continue
        seen.add(key)
        if c.rule_id not in quiet_exempt and in_quiet_period(
            repo.last_triggered_at(company.id, c.rule_id), now, quiet_hours
        ):
            logger.info("alert suppressed (quiet period)", extra={"symbol": company.symbol, "rule": c.rule_id})
            continue
        payload = {**c.model_dump(mode="json"), "name": company.name, "triggered_at": now.isoformat(),
                   "report_url": report_url}  # fmt: skip
        created.append(repo.add(Alert(company_id=company.id, rule_id=c.rule_id, severity=c.severity,
                                      triggered_at=now, payload=payload, deduplication_key=key)))  # fmt: skip
    return created


def deliver_pending(session: Session, notifier: Notifier, max_attempts: int) -> int:
    delivered = 0
    for alert in AlertRepo(session).undelivered(max_attempts):
        alert.attempts += 1
        try:
            notifier.send(alert.payload)
        except Exception as e:
            alert.delivery_status, alert.last_error = "failed", str(e)[:2000]
            logger.warning("alert delivery failed", extra={"alert_id": alert.id, "attempt": alert.attempts})
        else:
            alert.delivery_status, alert.delivered_at, alert.last_error = "sent", utcnow(), None
            delivered += 1
    session.flush()
    return delivered


def build_context(
    company: Company,
    entry: WatchlistCompany,
    ev: EvaluatedCompany,
    as_of: date,
    cfg: ScreeningConfig,
) -> AlertContext:
    since = entry.last_checked_at.date() if entry.last_checked_at else as_of - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    dq = ev.prepared.data_quality
    return AlertContext(
        symbol=company.symbol,
        exchange=company.exchange,
        as_of=as_of,
        since=since,
        values=ev.values,
        prev_values=entry.last_metrics or {},
        metrics=ev.prepared.metrics,
        announcements=ev.prepared.data.announcements,
        cfg=cfg.alerts.with_overrides(entry.alert_overrides),
        sector_group=ev.prepared.sector_group,
        valuation_range=entry.valuation_range,
        invalidation_conditions=entry.invalidation_conditions or [],
        data_quality_warnings=[i.message for i in dq.issues if i.severity in ("error", "warning")],
    )


def evaluate_watchlist_entry(
    session: Session,
    company: Company,
    entry: WatchlistCompany,
    ev: EvaluatedCompany,
    as_of: date,
    cfg: ScreeningConfig,
    *,
    quiet_hours: int,
    report_base_url: str,
) -> list[Alert]:
    candidates = evaluate_alert_rules(build_context(company, entry, ev, as_of, cfg))
    latest = ReportRepo(session).latest_for_company(company.id)
    url = f"{report_base_url}/research/reports/{latest.id}" if latest else None
    alerts = record_alerts(session, company, candidates, quiet_hours=quiet_hours,
                           quiet_exempt=cfg.alerts.quiet_period_exempt, report_url=url)  # fmt: skip
    if any(c.rule_id == "thesis_review" and c.severity == "critical" for c in candidates):
        entry.needs_review = True
    entry.last_metrics = {k: v for k, v in ev.values.items() if v is not None}
    entry.last_checked_at = utcnow()
    return alerts


def sector_medians_from_latest_run(session: Session, sector: str | None) -> dict[str, float] | None:
    run = ScreeningRepo(session).latest_completed_run()
    if not run or not sector:
        return None
    return (run.summary or {}).get("sector_medians", {}).get(sector)


def run_monitoring(
    session: Session,
    providers: Providers,
    cfg: ScreeningConfig,
    as_of: date,
    notifier: Notifier,
    *,
    quiet_hours: int,
    max_attempts: int,
    report_base_url: str,
) -> MonitoringRunOut:
    """Daily job: refresh each watchlisted company, evaluate alert rules, deliver."""
    entries = WatchlistRepo(session).all_entries()
    errors: list[str] = []
    created = 0
    evaluated_cache: dict[int, EvaluatedCompany] = {}
    for entry, company in entries:
        try:
            ev = evaluated_cache.get(company.id)
            if ev is None:
                data = fetch_company_data(providers, provider_symbol(company), as_of)
                group = apply_profile(company, data.profile)
                persist_company_data(session, company, data)
                prepared = prepare(data, company.sector, group, as_of, cfg)
                ev = evaluate(prepared, sector_medians_from_latest_run(session, company.sector), as_of, cfg)
                evaluated_cache[company.id] = ev
            created += len(evaluate_watchlist_entry(session, company, entry, ev, as_of, cfg,
                                                    quiet_hours=quiet_hours, report_base_url=report_base_url))  # fmt: skip
            session.commit()
        except Exception as e:
            session.rollback()
            errors.append(f"{company.symbol}: {type(e).__name__}: {e}")
            logger.exception("monitoring failed for company", extra={"symbol": company.symbol})
    delivered = deliver_pending(session, notifier, max_attempts)
    session.commit()
    return MonitoringRunOut(
        companies_checked=len({c.id for _, c in entries}), alerts_created=created, alerts_delivered=delivered,
        errors=errors,
    )  # fmt: skip
