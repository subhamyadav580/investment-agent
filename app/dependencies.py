"""FastAPI dependency providers. Tests override these via app.dependency_overrides."""

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.services.alerts.notifier import Notifier, build_notifier
from app.services.data.providers.registry import Providers, get_providers
from app.services.discovery.rules_config import ScreeningConfig, load_screening_config
from app.services.graph.llm import StructuredLLM
from app.services.graph.llm_factory import build_llm


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_data_providers() -> Providers:
    return get_providers()


def get_screening_config(settings: Settings = Depends(get_settings)) -> ScreeningConfig:
    return load_screening_config(settings.screening_rules_path)


def get_llm(settings: Settings = Depends(get_settings)) -> StructuredLLM:
    return build_llm(settings)


def get_notifier(settings: Settings = Depends(get_settings)) -> Notifier:
    return build_notifier(settings)
