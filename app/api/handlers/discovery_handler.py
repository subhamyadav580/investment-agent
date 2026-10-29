from datetime import date

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.dependencies import get_data_providers, get_db, get_screening_config
from app.repos.screening_repo import ScreeningRepo
from app.schemas.screening import ScreeningRunOut
from app.services.data.price_sync import sync_prices
from app.services.data.providers.base import ProviderError
from app.services.data.providers.registry import Providers, build_http_client
from app.services.discovery.event_discovery import EventFeedUnavailable, run_event_discovery
from app.services.discovery.rules_config import ScreeningConfig


def discover_from_events(
    as_of_date: date | None = None,
    days: int | None = None,
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_data_providers),
    cfg: ScreeningConfig = Depends(get_screening_config),
) -> ScreeningRunOut:
    try:
        run = run_event_discovery(db, providers, cfg, as_of_date or date.today(), days)
    except EventFeedUnavailable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ProviderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"data provider failed: {e}") from e
    return ScreeningRunOut.model_validate(run, from_attributes=True)


def industry_trends(run_id: int | None = None, improving_only: bool = False, db: Session = Depends(get_db)) -> dict:
    repo = ScreeningRepo(db)
    run = repo.get_run(run_id) if run_id else repo.latest_completed_run("universe")
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no screening run found")
    trends = (run.summary or {}).get("industry_trends", {})
    if improving_only:
        trends = {k: v for k, v in trends.items() if v["improving"]}
    return {"run_id": run.id, "as_of_date": run.as_of_date, "industries": trends}


def sync_exchange_prices(
    days: int = 10, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    out = sync_prices(db, build_http_client(settings), settings.price_sync_exchanges, days, date.today())
    return {"loaded": out.loaded, "missing": out.missing, "errors": out.errors}
