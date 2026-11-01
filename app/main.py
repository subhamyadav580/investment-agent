from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.routes import alerts, discovery, health, research, screening, ui, watchlist


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title="Investment Agent",
        description="Research and alerting assistant for NSE/BSE equities. Research only - no trade execution.",
        version="0.1.0",
    )
    for module in (health, screening, discovery, research, watchlist, alerts, ui):
        app.include_router(module.router)
    ui.mount(app)
    return app


app = create_app()
