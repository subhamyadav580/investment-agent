from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"

router = APIRouter(include_in_schema=False)


@router.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/ui/")


def mount(app: FastAPI) -> None:
    # Static files only; the page calls the JSON API with the X-API-Key the user enters, so no data is public.
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
