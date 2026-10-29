"""Exercises the real Anthropic SDK call path against a mocked HTTP transport (no network, no spend)."""

import json

import anthropic
import httpx2 as httpx

from app.core.config import Settings
from app.schemas.research import ValuationCommentary
from app.services.graph.llm import FALLBACK_BETA, ClaudeResearchLLM


def make_llm(handler, **overrides) -> ClaudeResearchLLM:
    client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                                 max_retries=0)  # fmt: skip
    return ClaudeResearchLLM(Settings(llm_enabled=True, **overrides), client=client)


def message(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
    }  # fmt: skip


def test_request_shape_and_parsed_output():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["beta"] = request.headers.get("anthropic-beta", "")
        return httpx.Response(200, json=message(json.dumps({"summary": "fine", "claims": []})))

    res = make_llm(handler).structured(task="t", system="sys", user="ctx", output_model=ValuationCommentary)
    assert res.output == ValuationCommentary(summary="fine", claims=[])
    assert res.meta["input_tokens"] == 1200 and "error" not in res.meta
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default" and FALLBACK_BETA in seen["beta"]
    assert "tools" not in body  # the model gets no tools
    assert "thinking" not in body and "temperature" not in body


def test_refusal_and_truncation_degrade_to_none():
    for stop, code in (("refusal", "refusal"), ("max_tokens", "truncated")):
        llm = make_llm(lambda r, s=stop: httpx.Response(200, json=message("{}", s)))
        res = llm.structured(task="t", system="s", user="u", output_model=ValuationCommentary)
        assert res.output is None and res.meta["error"] == code


def test_api_errors_degrade_to_none():
    llm = make_llm(lambda r: httpx.Response(429, json={"type": "error", "error": {"type": "rate_limit_error",
                                                                                   "message": "slow down"}}))  # fmt: skip
    res = llm.structured(task="t", system="s", user="u", output_model=ValuationCommentary)
    assert res.output is None and res.meta["error"] == "rate_limited"


def test_fallback_can_be_disabled():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=message(json.dumps({"summary": "x", "claims": []})))

    make_llm(handler, llm_refusal_fallback=False).structured(task="t", system="s", user="u",
                                                             output_model=ValuationCommentary)  # fmt: skip
    assert "fallbacks" not in seen["body"]


def test_disabled_llm_makes_no_call():
    res = ClaudeResearchLLM(Settings(llm_enabled=False)).structured(
        task="t", system="s", user="u", output_model=ValuationCommentary
    )
    assert res.output is None and res.meta["error"] == "llm_disabled"


def test_schema_violation_is_invalid_output():
    llm = make_llm(lambda r: httpx.Response(200, json=message(json.dumps({"summary": 3}))))
    res = llm.structured(task="t", system="s", user="u", output_model=ValuationCommentary)
    assert res.output is None and res.meta["error"] == "invalid_output"
