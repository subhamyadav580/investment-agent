"""Claude wrapper for structured research outputs.

- Output is constrained to a Pydantic schema (structured outputs) and validated by the SDK.
- Every failure mode (disabled, no credentials, API error, refusal, truncation, invalid output) returns
  output=None with the reason in `meta`, so the graph degrades to a deterministic-only "partial" report.
- No tools are exposed to the model: it cannot fetch data, place orders, or act; it only interprets context.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class LLMResult[T: BaseModel]:
    output: T | None
    meta: dict[str, Any] = field(default_factory=dict)


class StructuredLLM(Protocol):
    model_version: str | None

    def structured(self, *, task: str, system: str, user: str, output_model: type[T]) -> LLMResult[T]: ...


class ClaudeResearchLLM:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self.enabled = settings.llm_enabled
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        self.max_tokens = settings.llm_max_tokens
        self.fallback = settings.llm_refusal_fallback
        self._client = client

    @property
    def model_version(self) -> str | None:
        return self.model if self.enabled else None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def structured(self, *, task: str, system: str, user: str, output_model: type[T]) -> LLMResult[T]:
        meta: dict[str, Any] = {"task": task, "model": self.model}
        if not self.enabled:
            return LLMResult(None, {**meta, "error": "llm_disabled"})
        kwargs: dict[str, Any] = {}
        if self.fallback:
            # Server-side refusal fallback: if this model declines, the API retries on a fallback model.
            kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            # create (not parse) so stop_reason is checked before the body is validated: a refusal or a
            # truncated response is a different failure from malformed output.
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": anthropic.transform_schema(output_model)},
                },
                **kwargs,
            )
        except anthropic.AuthenticationError as e:
            return self._fail(meta, "auth_error", e)
        except anthropic.BadRequestError as e:
            return self._fail(meta, "bad_request", e)
        except anthropic.RateLimitError as e:
            return self._fail(meta, "rate_limited", e)
        except anthropic.APIStatusError as e:
            return self._fail(meta, f"api_error_{e.status_code}", e)
        except anthropic.APIConnectionError as e:
            return self._fail(meta, "connection_error", e)
        except anthropic.AnthropicError as e:
            return self._fail(meta, "client_error", e)
        except TypeError as e:
            # The SDK raises TypeError when no API key / auth token / profile can be resolved.
            if "authentication" not in str(e):
                raise
            return self._fail(meta, "no_credentials", e)

        usage = resp.usage
        meta.update(
            served_by=resp.model,
            stop_reason=resp.stop_reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None),
        )
        if resp.stop_reason == "refusal":
            return LLMResult(None, {**meta, "error": "refusal"})
        if resp.stop_reason == "max_tokens":
            return LLMResult(None, {**meta, "error": "truncated"})
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            output = output_model.model_validate_json(text)
        except ValidationError as e:
            return self._fail(meta, "invalid_output", e)
        logger.info("llm call", extra={k: v for k, v in meta.items() if k != "model"})
        return LLMResult(output, meta)

    @staticmethod
    def _fail(meta: dict[str, Any], code: str, exc: Exception) -> LLMResult:
        logger.warning("llm call failed", extra={"task": meta["task"], "code": code, "error": str(exc)[:300]})
        return LLMResult(None, {**meta, "error": code, "detail": str(exc)[:500]})
