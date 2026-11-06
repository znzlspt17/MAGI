"""제공자 요청과 안전한 reasoning 관측 계약."""
import json

import httpx2
import pytest
from langchain_core.messages import AIMessage

from backend.providers.llm_provider import ChatModelProvider, completion_result
from tests.support.chat_model_fixture import transport
from tests.support.model_helpers import response


@pytest.mark.parametrize(("stage", "verbosity"), [("spec_compile", "high"), ("interview", "medium")])
def test_stage_policy_is_sent(stage, verbosity):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=response(), request=request)

    with transport(handle):
        ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "user", "content": "Request"}], model="gpt-6-luna",
            stage=stage, conversation_id="conv_test")
    body = requests[0]
    assert body["reasoning"] == {"mode": "standard", "effort": "medium", "summary": "auto"}
    assert body["text"]["verbosity"] == verbosity
    assert body["max_output_tokens"] == 128000
    assert not ({"seed", "top_k", "top_p", "temperature"} & body.keys())


def test_summary_observation_is_bounded_and_excludes_other_content():
    result = completion_result(AIMessage(content=[
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "가" * 8001}],
         "encrypted_content": "hidden"},
        {"type": "text", "text": "result"},
    ], usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7,
                       "output_token_details": {"reasoning": 0}}))
    assert result.reasoning_summary == "가" * 8000
    assert result.summary_truncated is True
    assert result.reasoning_tokens == 0
    assert "hidden" not in repr(result)


def test_absent_and_invalid_summary_are_not_fabricated():
    result = completion_result(AIMessage(content=[{"type": "reasoning", "summary": [{"type": "summary_text", "text": 12}]}]))
    assert result.reasoning_summary is None
    assert result.reasoning_tokens is None
    assert result.summary_truncated is False


def test_normalized_reasoning_summary_is_observed():
    result = completion_result(AIMessage(content=[{"type": "reasoning", "reasoning": "판단 요약"}]))
    assert result.reasoning_summary == "판단 요약"


def test_response_reasoning_summary_and_zero_usage_survive_http_observation():
    payload = response()
    payload["output"].insert(0, {"type": "reasoning", "id": "rs_1", "summary": [
        {"type": "summary_text", "text": "판단 근거"}], "encrypted_content": "never-store"})
    payload["usage"]["output_tokens_details"] = {"reasoning_tokens": 0}

    def handle(request):
        return httpx2.Response(200, json=payload, request=request)

    with transport(handle):
        result = ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "user", "content": "Request"}], model="gpt-6-luna",
            stage="interview", conversation_id="conv_test")
    assert result.reasoning_summary == "판단 근거"
    assert result.reasoning_tokens == 0
    assert "never-store" not in repr(result)


def test_native_tool_call_preserves_schema_and_result_precedence():
    from pydantic import BaseModel

    class Final(BaseModel):
        answer: str

    tool = {"type": "function", "function": {"name": "search", "description": "search",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}, "strict": False}}
    payload = response()
    payload["output"] = [
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
         "content": [{"type": "output_text", "text": "선행 설명", "annotations": []}]},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "search",
         "arguments": '{"query":"term"}', "status": "completed"},
    ]
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=payload, request=request)

    with transport(handle):
        result = ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "tool", "tool_call_id": "call_previous", "content": "tool output"},
             {"role": "user", "content": "request"}], model="gpt-6-luna",
            stage="interview", text_format=Final, conversation_id="conv_test",
            instructions="current instruction", tools=[tool], tool_choice="auto")
    assert result.parsed is None
    assert result.tool_calls == [{"id": "call_1", "name": "search", "args": {"query": "term"}}]
    body = requests[0]
    assert body["input"][0]["type"] == "function_call_output"
    assert body["input"][0]["call_id"] == "call_previous"
    assert body["input"][1]["role"] == "developer"
    assert body["tools"][0]["strict"] is False
    assert body["text"]["format"]["strict"] is True
    assert body["parallel_tool_calls"] is False
    assert all(item.get("role") != "assistant" for item in body["input"])


def test_native_tool_limit_returns_strict_final_json():
    from pydantic import BaseModel

    class Final(BaseModel):
        answer: str

    requests = []
    payload = response(content=[{"type": "output_text", "text": '{"answer":"ok"}', "annotations": []}])

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=payload, request=request)

    with transport(handle):
        result = ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "user", "content": "request"}], model="gpt-6-luna",
            stage="interview", text_format=Final, conversation_id="conv_test",
            tools=[], tool_choice="none")
    assert result.parsed == Final(answer="ok") and result.tool_calls == []
    assert requests[0]["tool_choice"] == "none"
    assert requests[0]["text"]["format"]["strict"] is True


def test_invalid_native_arguments_remain_recoverable_with_call_id():
    from pydantic import BaseModel

    class Final(BaseModel):
        answer: str

    tool = {"type": "function", "function": {"name": "search", "description": "search",
            "parameters": {"type": "object", "properties": {}}, "strict": False}}
    payload = response()
    payload["output"] = [{"type": "function_call", "id": "fc_1", "call_id": "call_1",
                          "name": "search", "arguments": "{broken", "status": "completed"}]

    def handle(request):
        return httpx2.Response(200, json=payload, request=request)

    with transport(handle):
        result = ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "user", "content": "request"}], model="gpt-6-luna",
            stage="interview", text_format=Final, conversation_id="conv_test", tools=[tool])
    assert result.tool_calls[0]["id"] == "call_1"
    assert isinstance(result.tool_calls[0]["args"], str)
    assert result.parsed is None
