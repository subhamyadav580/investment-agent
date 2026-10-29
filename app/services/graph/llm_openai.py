"""OpenAI wrapper for structured research outputs (Responses API + strict JSON schema).

Same contract as the Claude wrapper: every failure mode returns output=None with the reason in `meta`, so the
graph degrades to a deterministic-only "partial" report. No tools are exposed to the model.
"""

import logging
from typing import Any

import openai
from openai.lib._pydantic import to_strict_json_schema  # SDK helper that builds strict-mode schemas
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.services.graph.llm import LLMResult

logger = logging.getLogger(__name__)


class OpenAIResearchLLM:
    def __init__(self, settings: Settings, client: openai.OpenAI | None = None):
        self.enabled = settings.llm_enabled
        self.model = settings.openai_model
        self.reasoning_effort = settings.openai_reasoning_effort
        self.max_tokens = settings.llm_max_tokens
        self._client = client

    @property
    def model_version(self) -> str | None:
        return self.model if self.enabled else None

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            self._client = openai.OpenAI()  # reads OPENAI_API_KEY
        return self._client

    def structured[T: BaseModel](self, *, task: str, system: str, user: str, output_model: type[T]) -> LLMResult[T]:
        meta: dict[str, Any] = {"task": task, "model": self.model}
        if not self.enabled:
            return LLMResult(None, {**meta, "error": "llm_disabled"})
        kwargs: dict[str, Any] = {}
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        try:
            # create (not parse) so status/refusal are checked before the body is validated.
            resp = self.client.responses.create(
                model=self.model,
                instructions=system,
                input=user,
                max_output_tokens=self.max_tokens,
                store=False,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": output_model.__name__,
                        "schema": to_strict_json_schema(output_model),
                        "strict": True,
                    }
                },
                **kwargs,
            )
        except openai.AuthenticationError as e:
            return self._fail(meta, "auth_error", e)
        except openai.BadRequestError as e:
            return self._fail(meta, "bad_request", e)
        except openai.RateLimitError as e:
            return self._fail(meta, "rate_limited", e)
        except openai.APIStatusError as e:
            return self._fail(meta, f"api_error_{e.status_code}", e)
        except openai.APIConnectionError as e:
            return self._fail(meta, "connection_error", e)
        except openai.OpenAIError as e:  # includes a missing OPENAI_API_KEY at client construction
            code = "no_credentials" if "api_key" in str(e) else "client_error"
            return self._fail(meta, code, e)

        usage = resp.usage
        meta.update(
            served_by=resp.model,
            status=resp.status,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cached_input_tokens=getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None),
        )
        if resp.status == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", None)
            return LLMResult(None, {**meta, "error": "truncated" if reason == "max_output_tokens" else f"incomplete_{reason}"})

        text_parts, refused = [], False
        for item in resp.output:
            if item.type != "message":
                continue  # reasoning items etc.
            for part in item.content:
                if part.type == "refusal":
                    refused = True
                elif part.type == "output_text":
                    text_parts.append(part.text)
        if refused:
            return LLMResult(None, {**meta, "error": "refusal"})
        try:
            output = output_model.model_validate_json("".join(text_parts))
        except ValidationError as e:
            return self._fail(meta, "invalid_output", e)
        logger.info("llm call", extra={k: v for k, v in meta.items() if k != "model"})
        return LLMResult(output, meta)

    @staticmethod
    def _fail(meta: dict[str, Any], code: str, exc: Exception) -> LLMResult:
        logger.warning("llm call failed", extra={"task": meta["task"], "code": code, "error": str(exc)[:300]})
        return LLMResult(None, {**meta, "error": code, "detail": str(exc)[:500]})
