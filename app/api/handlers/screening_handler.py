from datetime import date

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_data_providers, get_db, get_screening_config
from app.models import ScreeningRun
from app.repos.screening_repo import ScreeningRepo
from app.schemas.screening import (
    ScreeningResultOut,
    ScreeningRunDetailOut,
    ScreeningRunOut,
    ScreeningRunRequest,
)
from app.services.data.providers.base import ProviderError
from app.services.data.providers.registry import Providers
from app.services.discovery.rules_config import ScreeningConfig
from app.services.discovery.screening_service import run_screening


def _run_out(run: ScreeningRun) -> ScreeningRunOut:
    return ScreeningRunOut.model_validate(run, from_attributes=True)


def create_run(
    body: ScreeningRunRequest,
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_data_providers),
    cfg: ScreeningConfig = Depends(get_screening_config),
) -> ScreeningRunOut:
    try:
        run = run_screening(db, providers, cfg, body.as_of_date or date.today(), body.enqueue_top_n)
    except ProviderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"data provider failed: {e}") from e
    return _run_out(run)


def list_runs(limit: int = 20, db: Session = Depends(get_db)) -> list[ScreeningRunOut]:
    return [_run_out(r) for r in ScreeningRepo(db).list_runs(limit)]


def get_run(run_id: int, result_status: str | None = None, db: Session = Depends(get_db)) -> ScreeningRunDetailOut:
    repo = ScreeningRepo(db)
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"screening run {run_id} not found")
    results = [
        ScreeningResultOut(
            symbol=c.symbol, name=c.name, sector=c.sector, status=r.status, score=r.score, rank=r.rank,
            dimension_scores=r.dimension_scores, passed_rules=r.passed_rules, failed_rules=r.failed_rules,
            exclusion_reasons=r.exclusion_reasons, data_quality=r.data_quality,
        )  # fmt: skip
        for r, c in repo.results_for_run(run_id, result_status)
    ]
    return ScreeningRunDetailOut(**_run_out(run).model_dump(), results=results)
