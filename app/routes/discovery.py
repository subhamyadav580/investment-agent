from fastapi import APIRouter, Depends

from app.api.handlers import discovery_handler as h
from app.schemas.screening import ScreeningRunOut
from app.utils.auth import require_api_key

router = APIRouter(prefix="/discovery", tags=["discovery"], dependencies=[Depends(require_api_key)])

router.add_api_route("/events", h.discover_from_events, methods=["POST"], response_model=ScreeningRunOut, status_code=201)
router.add_api_route("/industries", h.industry_trends, methods=["GET"])
router.add_api_route("/prices/sync", h.sync_exchange_prices, methods=["POST"])
