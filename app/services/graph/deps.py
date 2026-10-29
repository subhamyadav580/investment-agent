from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.data.providers.registry import Providers
from app.services.discovery.rules_config import ScreeningConfig
from app.services.graph.llm import StructuredLLM


@dataclass
class GraphDeps:
    """Everything the nodes need, injected once per graph build (no globals inside nodes)."""

    session: Session
    providers: Providers
    cfg: ScreeningConfig
    llm: StructuredLLM
    prompt_version: str
    quiet_hours: int
    report_base_url: str
    max_fetch_attempts: int = 2
