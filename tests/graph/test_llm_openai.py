"""Exercises the real OpenAI SDK call path against a mocked HTTP transport (no network, no spend)."""

import json

import httpx2 as httpx
import openai
import pytest

from app.core.config import Settings
from app.schemas.research import RiskAnalysis, ValuationCommentary
from app.services.graph.llm import ClaudeResearchLLM
from app.services.graph.llm_factory import build_llm
from app.services.graph.llm_openai import OpenAIResearchLLM


def make_llm(handler, **overrides) -> OpenAIResearchLLM:
    client = openai.OpenAI(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                           max_retries=0)  # fmt: skip
    return OpenAIResearchLLM(Settings(llm_enabled=True, **overrides), client=client)


def response(content: list[dict], status: str = "completed", incomplete_reason: str | None = None) -> dict:
    return {
        "id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-5.5", "status": status,
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": content},
        ],
        "incomplete_details": {"reason": incomplete_reason} if incomplete_reason else None,
        "usage": {"input_tokens": 900, "output_tokens": 70, "total_tokens": 970,
                  "input_tokens_details": {"cached_tokens": 512}, "output_tokens_details": {"reasoning_tokens": 20}},
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "error": None, "metadata": {},
    }  # fmt: skip


def text(payload: dict) -> list[dict]:
    return [{"type": "output_text", "text": json.dumps(payload), "annotations": []}]


def test_request_shape_and_parsed_output():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=response(text({"summary": "fine", "scenario_commentary": "n/a", "medium_term_view": "n/a", "claims": []})))

    res = make_llm(handler).structured(task="t", system="sys", user="ctx", output_model=ValuationCommentary)
    assert res.output == ValuationCommentary(summary="fine", scenario_commentary="n/a", medium_term_view="n/a", claims=[])
    assert res.meta["input_tokens"] == 900 and res.meta["cached_input_tokens"] == 512 and "error" not in res.meta
    body = seen["body"]
    assert seen["path"].endswith("/responses")
    assert body["model"] == "gpt-5.5" and body["instructions"] == "sys" and body["input"] == "ctx"
    assert body["reasoning"] == {"effort": "medium"} and body["store"] is False
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "ValuationCommentary"
    assert fmt["schema"]["additionalProperties"] is False
    assert "tools" not in body  # the model gets no tools


def test_nested_models_produce_strict_schema():
    seen = {}

    def handler(request):
        seen["schema"] = json.loads(request.content)["text"]["format"]["schema"]
        return httpx.Response(200, json=response(text({"management_assessment": "", "risks": [], "downside_scenarios": [], "catalysts": [],
                                                        "monitor_next": [], "invalidation_conditions": []})))  # fmt: skip

    res = make_llm(handler).structured(task="t", system="s", user="u", output_model=RiskAnalysis)
    assert res.output is not None
    risk_item = seen["schema"]["$defs"]["RiskItem"]
    assert risk_item["additionalProperties"] is False and set(risk_item["required"]) == set(risk_item["properties"])


def test_refusal_truncation_and_bad_output_degrade_to_none():
    cases = [
        (response([{"type": "refusal", "refusal": "I can't help with that."}]), "refusal"),
        (response(text({"summary": "x"}), status="incomplete", incomplete_reason="max_output_tokens"), "truncated"),
        (response(text({"summary": 3})), "invalid_output"),
    ]
    for body, code in cases:
        llm = make_llm(lambda r, b=body: httpx.Response(200, json=b))
        res = llm.structured(task="t", system="s", user="u", output_model=ValuationCommentary)
        assert res.output is None and res.meta["error"] == code


def test_api_errors_degrade_to_none():
    for status, code in ((429, "rate_limited"), (401, "auth_error"), (500, "api_error_500")):
        llm = make_llm(lambda r, s=status: httpx.Response(s, json={"error": {"message": "x", "type": "e"}}))
        res = llm.structured(task="t", system="s", user="u", output_model=ValuationCommentary)
        assert res.output is None and res.meta["error"] == code


def test_reasoning_effort_can_be_omitted():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=response(text({"summary": "x", "claims": []})))

    make_llm(handler, openai_reasoning_effort="").structured(task="t", system="s", user="u",
                                                             output_model=ValuationCommentary)  # fmt: skip
    assert "reasoning" not in seen["body"]


def test_missing_api_key_degrades(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = OpenAIResearchLLM(Settings(llm_enabled=True)).structured(
        task="t", system="s", user="u", output_model=ValuationCommentary
    )
    assert res.output is None and res.meta["error"] == "no_credentials"


def test_factory_selects_provider():
    assert isinstance(build_llm(Settings(llm_provider="openai")), OpenAIResearchLLM)
    assert isinstance(build_llm(Settings(llm_provider="anthropic")), ClaudeResearchLLM)
    with pytest.raises(ValueError):
        build_llm(Settings(llm_provider="other"))
