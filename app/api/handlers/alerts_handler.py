from datetime import date

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.dependencies import get_data_providers, get_db, get_notifier, get_screening_config
from app.repos.alert_repo import AlertRepo
from app.schemas.alerts import AlertOut, MonitoringRunOut
from app.services.alerts.alert_service import deliver_pending, run_monitoring
from app.services.alerts.notifier import Notifier
from app.services.data.normalization import normalize_symbol
from app.services.data.providers.registry import Providers
from app.services.discovery.rules_config import ScreeningConfig


def list_alerts(
    symbol: str | None = None, delivery_status: str | None = None, limit: int = 100, db: Session = Depends(get_db)
) -> list[AlertOut]:
    rows = AlertRepo(db).search(normalize_symbol(symbol) if symbol else None, delivery_status, limit)
    return [
        AlertOut(id=a.id, symbol=c.symbol, rule_id=a.rule_id, severity=a.severity, triggered_at=a.triggered_at,
                 delivery_status=a.delivery_status, attempts=a.attempts, payload=a.payload)  # fmt: skip
        for a, c in rows
    ]


def run_monitoring_now(
    as_of_date: date | None = None,
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_data_providers),
    cfg: ScreeningConfig = Depends(get_screening_config),
    notifier: Notifier = Depends(get_notifier),
    settings: Settings = Depends(get_settings),
) -> MonitoringRunOut:
    return run_monitoring(
        db, providers, cfg, as_of_date or date.today(), notifier,
        quiet_hours=settings.alert_quiet_period_hours, max_attempts=settings.alert_max_delivery_attempts,
        report_base_url=settings.report_base_url,
    )  # fmt: skip


def retry_delivery(
    db: Session = Depends(get_db), notifier: Notifier = Depends(get_notifier), settings: Settings = Depends(get_settings)
) -> dict:
    return {"delivered": deliver_pending(db, notifier, settings.alert_max_delivery_attempts)}
