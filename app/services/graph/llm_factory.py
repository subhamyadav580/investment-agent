"""Strategy + Factory for the LLM provider. Adding a provider = one wrapper module + one branch here."""

from app.core.config import Settings
from app.services.graph.llm import ClaudeResearchLLM, StructuredLLM
from app.services.graph.llm_openai import OpenAIResearchLLM


def build_llm(settings: Settings) -> StructuredLLM:
    match settings.llm_provider:
        case "openai":
            return OpenAIResearchLLM(settings)
        case "anthropic":
            return ClaudeResearchLLM(settings)
        case other:
            raise ValueError(f"unknown LLM_PROVIDER {other!r} (expected 'openai' or 'anthropic')")
