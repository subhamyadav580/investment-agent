from fastapi import Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_data_providers, get_db
from app.models import Company, Watchlist, WatchlistCompany
from app.schemas.watchlist import WatchlistCompanyIn, WatchlistCompanyOut, WatchlistCreate, WatchlistOut
from app.services.data.providers.registry import Providers
from app.services.watchlist.watchlist_service import Conflict, NotFound, WatchlistService


def _service(db: Session, providers: Providers) -> WatchlistService:
    return WatchlistService(db, providers.universe)


def _entry_out(e: WatchlistCompany, c: Company) -> WatchlistCompanyOut:
    return WatchlistCompanyOut(
        symbol=c.symbol, name=c.name, thesis=e.thesis, assumptions=e.assumptions,
        invalidation_conditions=e.invalidation_conditions, alert_overrides=e.alert_overrides,
        valuation_range=e.valuation_range, review_date=e.review_date, needs_review=e.needs_review,
        last_checked_at=e.last_checked_at, added_at=e.added_at,
    )  # fmt: skip


def _watchlist_out(wl: Watchlist, entries) -> WatchlistOut:
    return WatchlistOut(id=wl.id, name=wl.name, created_at=wl.created_at, companies=[_entry_out(e, c) for e, c in entries])


def _http(e: Exception) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(e, NotFound) else status.HTTP_409_CONFLICT
    return HTTPException(code, str(e))


def create_watchlist(
    body: WatchlistCreate, db: Session = Depends(get_db), providers: Providers = Depends(get_data_providers)
) -> WatchlistOut:
    try:
        wl = _service(db, providers).create(body.name)
    except Conflict as e:
        raise _http(e) from e
    return _watchlist_out(wl, [])


def list_watchlists(db: Session = Depends(get_db), providers: Providers = Depends(get_data_providers)) -> list[WatchlistOut]:
    return [_watchlist_out(wl, entries) for wl, entries in _service(db, providers).list_all()]


def get_watchlist(
    watchlist_id: int, db: Session = Depends(get_db), providers: Providers = Depends(get_data_providers)
) -> WatchlistOut:
    try:
        return _watchlist_out(*_service(db, providers).get(watchlist_id))
    except NotFound as e:
        raise _http(e) from e


def upsert_company(
    watchlist_id: int,
    body: WatchlistCompanyIn,
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_data_providers),
) -> WatchlistCompanyOut:
    try:
        return _entry_out(*_service(db, providers).upsert_company(watchlist_id, body))
    except (NotFound, Conflict) as e:
        raise _http(e) from e


def remove_company(
    watchlist_id: int, symbol: str, db: Session = Depends(get_db), providers: Providers = Depends(get_data_providers)
) -> Response:
    try:
        _service(db, providers).remove_company(watchlist_id, symbol)
    except NotFound as e:
        raise _http(e) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
