from fastapi import APIRouter, Depends

from app.api.handlers import watchlist_handler as h
from app.schemas.watchlist import WatchlistCompanyOut, WatchlistOut
from app.utils.auth import require_api_key

router = APIRouter(prefix="/watchlists", tags=["watchlists"], dependencies=[Depends(require_api_key)])

router.add_api_route("", h.create_watchlist, methods=["POST"], response_model=WatchlistOut, status_code=201)
router.add_api_route("", h.list_watchlists, methods=["GET"], response_model=list[WatchlistOut])
router.add_api_route("/{watchlist_id}", h.get_watchlist, methods=["GET"], response_model=WatchlistOut)
router.add_api_route(
    "/{watchlist_id}/companies", h.upsert_company, methods=["PUT"], response_model=WatchlistCompanyOut
)
router.add_api_route("/{watchlist_id}/companies/{symbol}", h.remove_company, methods=["DELETE"], status_code=204)
