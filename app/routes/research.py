from fastapi import APIRouter, Depends

from app.api.handlers import research_handler as h
from app.schemas.research import (
    QueueProcessOut,
    ResearchReportOut,
    ResearchReportSummaryOut,
    ShortlistItemOut,
)
from app.utils.auth import require_api_key

router = APIRouter(prefix="/research", tags=["research"], dependencies=[Depends(require_api_key)])

router.add_api_route("", h.run_research, methods=["POST"], response_model=ResearchReportOut, status_code=201)
# /queue/process must be registered before /queue/{symbol}
router.add_api_route("/queue/process", h.process_queue, methods=["POST"], response_model=QueueProcessOut)
router.add_api_route("/queue/{symbol}", h.enqueue_research, methods=["POST"], status_code=202)
router.add_api_route("/shortlist", h.get_shortlist, methods=["GET"], response_model=list[ShortlistItemOut])
router.add_api_route("/reports", h.list_reports, methods=["GET"], response_model=list[ResearchReportSummaryOut])
router.add_api_route("/reports/{report_id}", h.get_report, methods=["GET"], response_model=ResearchReportOut)
