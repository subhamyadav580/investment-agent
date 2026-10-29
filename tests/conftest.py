import os

# Must be set before app modules read settings.
os.environ.update(
    {
        "DATABASE_URL": "sqlite://",
        "API_KEY": "test-key",
        "LLM_ENABLED": "false",
        "NOTIFICATION_CHANNELS": '["log"]',
        "UNIVERSE_PROVIDER": "fixture",
        "FUNDAMENTALS_PROVIDER": "fixture",
        "MARKET_DATA_PROVIDER": "fixture",
        "ANNOUNCEMENTS_PROVIDER": "fixture",
        "LOG_JSON": "false",
    }
)

from datetime import date  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import Settings, get_settings  # noqa: E402

Settings.model_config["env_file"] = None  # tests must not depend on the developer's .env
from app.db.base import Base  # noqa: E402
from app.services.data.providers.registry import build_providers  # noqa: E402
from app.services.discovery.rules_config import load_screening_config  # noqa: E402
from app.services.graph.llm import LLMResult  # noqa: E402

AS_OF = date(2026, 10, 24)


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def cfg(settings):
    return load_screening_config(settings.screening_rules_path)


@pytest.fixture
def providers(settings):
    return build_providers(settings)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session(session_factory) -> Session:
    s = session_factory()
    yield s
    s.close()


class FakeLLM:
    """Returns canned structured outputs per output model; records every call."""

    model_version = "fake-llm"

    def __init__(self, outputs: dict[type, Any] | None = None, error: str | None = None):
        self.outputs = outputs or {}
        self.error = error
        self.calls: list[dict] = []

    def structured(self, *, task, system, user, output_model):
        self.calls.append({"task": task, "system": system, "user": user})
        if self.error:
            return LLMResult(None, {"task": task, "error": self.error})
        out = self.outputs.get(output_model)
        meta = {"task": task, "input_tokens": 100, "output_tokens": 50}
        return LLMResult(out, meta if out else {**meta, "error": "no_canned_output"})
