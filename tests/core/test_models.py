"""공식 LangChain 통합의 요청과 표준 사용량을 외부 통신 없이 검증한다."""

import json
from unittest.mock import Mock, patch
import httpx2
import pytest
from langchain_core.messages import AIMessage

from backend.errors import Error
from backend.providers.llm_provider import ChatModelProvider, completion_result
from chat_model_fixture import transport


def response(status="completed", content=None):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6-luna",
        "status": status,
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": content
                if content is not None
                else [{"type": "output_text", "text": "Result", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 3,
            "total_tokens": 23,
            "input_tokens_details": {"cached_tokens": 10},
        },
    }


def invoke(payload, *, status=200, model="gpt-6-luna"):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx2.Response(status, json=payload, request=request)

    with transport(handle):
        result = ChatModelProvider(api_key="fake-test-value").complete_result(
            [
                {"role": "system", "content": "Instructions"},
                {"role": "user", "content": "Request"},
            ],
            model=model,
            temperature=0,
            cache_key="test-stage",
        )
    return result, requests


def test_langchain_responses_request_and_usage():
    result, requests = invoke(response())
    assert len(requests) == 1 and requests[0].url.path == "/v1/responses"
    body = json.loads(requests[0].content)
    assert body["model"] == "gpt-6-luna" and body["service_tier"] == "default"
    assert body["max_output_tokens"] == 128_000
    assert body["input"][0] == {
        "role": "system",
        "content": "Instructions",
        "type": "message",
    }
    assert body["input"][1] == {"role": "user", "content": "Request", "type": "message"}
    assert "conversation" not in body and "previous_response_id" not in body
    assert "temperature" not in body and body["prompt_cache_key"] == "test-stage"
    assert result.text == "Result"
    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == (
        20,
        3,
        10,
    )
    assert result.cache_write_tokens is None


def test_standard_usage_missing_is_not_zero():
    result = completion_result(AIMessage(content="Result"))
    assert result.input_tokens is result.output_tokens is result.cached_tokens is None
    result = completion_result(
        AIMessage(
            content="Result",
            usage_metadata={
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "input_token_details": {"cache_read": 0},
            },
        )
    )
    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == (
        0,
        0,
        0,
    )


def test_adapter_preserves_aggregate_writes_without_inventing_lifetimes():
    payload = response()
    payload["usage"]["input_tokens_details"].update(cache_write_tokens=7)
    result, _ = invoke(payload)
    assert result.cache_write_tokens == 7
    assert (
        result.cache_write_30m_tokens is None and result.cache_write_12h_tokens is None
    )


def test_explicit_instructions_override_source_system_message():
    llm = Mock()
    llm.invoke.return_value = AIMessage(content="Result")
    with patch(
        "backend.providers.llm_provider.init_chat_model", return_value=llm
    ) as factory:
        ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "system", "content": "Superseded"}],
            model="gpt-6-luna",
            instructions="Current",
        )
    assert llm.invoke.call_args.args[0] == [{"role": "system", "content": "Current"}]
    assert factory.call_args.kwargs["max_retries"] == 0
    assert factory.call_args.kwargs["use_previous_response_id"] is False


@pytest.mark.parametrize(
    "payload",
    [
        response(content=[]),
        response("incomplete"),
        response(content=[{"type": "refusal", "refusal": "DO_NOT_PROPAGATE"}]),
    ],
)
def test_empty_incomplete_refused_response_fails(payload):
    with pytest.raises(Error):
        invoke(payload)


def test_integration_error_is_sanitized():
    with pytest.raises(Error) as error:
        invoke(
            {"error": {"message": "DO_NOT_PROPAGATE", "type": "invalid_request_error"}},
            status=400,
        )
    assert (
        "DO_NOT_PROPAGATE" not in str(error.value) and error.value.__suppress_context__
    )


def test_structured_output_parse_failure_keeps_observed_usage():
    from pydantic import BaseModel

    class Output(BaseModel):
        value: str

    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json=response(
                content=[
                    {"type": "output_text", "text": '{"value":"ok"}', "annotations": []}
                ]
            ),
            request=request,
        )

    with transport(handle):
        result = ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "user", "content": "Request"}],
            model="gpt-6-luna",
            text_format=Output,
        )
    assert result.parsed.value == "ok"
    assert requests[0]["text"]["format"]["type"] == "json_schema"

    def invalid(request):
        return httpx2.Response(
            200,
            json=response(
                content=[{"type": "output_text", "text": "{broken", "annotations": []}]
            ),
            request=request,
        )

    with transport(invalid), pytest.raises(Error) as failure:
        ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "user", "content": "Request"}],
            model="gpt-6-luna",
            text_format=Output,
        )
    assert failure.value.completion.input_tokens == 20
