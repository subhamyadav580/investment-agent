from fastapi import APIRouter, Depends

from app.api.handlers import alerts_handler as h
from app.schemas.alerts import AlertOut, MonitoringRunOut
from app.utils.auth import require_api_key

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_api_key)])

router.add_api_route("", h.list_alerts, methods=["GET"], response_model=list[AlertOut])
router.add_api_route("/monitor", h.run_monitoring_now, methods=["POST"], response_model=MonitoringRunOut)
router.add_api_route("/deliver", h.retry_delivery, methods=["POST"])
