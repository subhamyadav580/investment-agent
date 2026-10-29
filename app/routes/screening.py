from fastapi import APIRouter, Depends

from app.api.handlers import screening_handler as h
from app.schemas.screening import ScreeningRunDetailOut, ScreeningRunOut
from app.utils.auth import require_api_key

router = APIRouter(prefix="/screening", tags=["screening"], dependencies=[Depends(require_api_key)])

router.add_api_route("/runs", h.create_run, methods=["POST"], response_model=ScreeningRunOut, status_code=201)
router.add_api_route("/runs", h.list_runs, methods=["GET"], response_model=list[ScreeningRunOut])
router.add_api_route("/runs/{run_id}", h.get_run, methods=["GET"], response_model=ScreeningRunDetailOut)
