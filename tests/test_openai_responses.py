"""실제 SDK의 요청 직렬화와 응답 처리를 외부 통신 없이 검증한다."""

import json
from unittest.mock import patch

import httpx2
import pytest
from openai import OpenAI

from backend.config import MagiConfig
from backend.errors import MagiError
from backend.providers.llm_provider import OpenAIProvider
from backend.server.job_manager import JobManager


def invoke(payload, *, status=200, model="gpt-6-luna"):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx2.Response(status, json=payload, request=request)

    client = OpenAI(
        api_key="fake-test-value", max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handle)),
    )
    with patch("backend.providers.llm_provider.OpenAI", return_value=client):
        result = OpenAIProvider(api_key="fake-test-value").complete_result(
            [{"role": "system", "content": "Instructions"},
             {"role": "user", "content": "Request"}],
            model=model, temperature=0, cache_key="test-stage",
        )
    return result, requests


def response(status="completed", content=None):
    return {
        "id": "resp_test", "object": "response", "created_at": 1,
        "model": "gpt-6-luna", "status": status,
        "output": [{"type": "message", "id": "msg_test", "role": "assistant",
                    "status": "completed", "content": content if content is not None else
                    [{"type": "output_text", "text": "Result", "annotations": []}]}],
        "usage": {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23,
                  "input_tokens_details": {"cached_tokens": 10}},
    }


def test_sdk_responses_request_and_usage():
    result, requests = invoke(response())
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/responses"
    body = json.loads(requests[0].content)
    assert body['model']=='gpt-6-luna'
    assert body['service_tier']=='default'
    assert body['max_output_tokens']==128_000
    assert body["instructions"] == "Instructions"
    assert body["input"] == [{"role": "user", "content": "Request"}]
    assert body["prompt_cache_options"] == {"mode": "implicit", "ttl": "30m"}
    assert "temperature" not in body
    assert body["prompt_cache_key"] == "test-stage"
    assert result.text == "Result"
    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == (20, 3, 10)


def test_stable_boundaries_survive_changing_suffix_and_sdk_serialization():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=response(), request=request)

    messages = [
        {"role": "user", "content": "Original user request (immutable):\nOriginal"},
        {"role": "user", "content": "Canonical context:\n" + "Stable reference. " * 1500},
    ]
    original = json.dumps(messages)
    for suffix in ("First feedback", "Changed feedback"):
        client = OpenAI(api_key="fake-test-value", max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))
        with patch("backend.providers.llm_provider.OpenAI", return_value=client):
            OpenAIProvider(api_key="fake-test-value").complete_result(
                [*messages, {"role": "user", "content": suffix}], model="gpt-6-luna",
                instructions="Fixed instructions", cache_key="same-stage")
    assert requests[0]["input"][:2] == requests[1]["input"][:2]
    assert requests[0]["input"][2] != requests[1]["input"][2]
    for body in requests:
        assert body["prompt_cache_options"]["mode"] == "implicit"
        assert body["instructions"] == "Fixed instructions"
        assert len(body["input"]) == 3
        for item in body["input"][:2]:
            assert item["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
        assert isinstance(body["input"][2]["content"], str)
    assert json.dumps(messages) == original


def test_explicit_instructions_override_source_system_message():
    from unittest.mock import MagicMock

    result = MagicMock(status="completed", output_text="Result")
    result.model_dump.return_value = response()
    with patch("backend.providers.llm_provider.OpenAI") as factory:
        create = factory.return_value.__enter__.return_value.responses.create
        create.return_value = result
        OpenAIProvider(api_key="fake-test-value").complete_result(
            [{"role": "system", "content": "Superseded instruction"}],
            model="gpt-6-luna", instructions="Current instruction", conversation_id="conv_before")
        body = create.call_args.kwargs
    assert body["conversation"] == "conv_before"
    assert "previous_response_id" not in body
    assert body["instructions"] == "Current instruction"
    assert "Superseded" not in json.dumps(body)


def test_empty_response_fails():
    payload = response(content=[])
    with pytest.raises(MagiError):
        invoke(payload)


def test_sdk_error_is_sanitized():
    with pytest.raises(MagiError) as error:
        invoke({"error": {"message": "DO_NOT_PROPAGATE", "type": "invalid_request_error"}}, status=400)
    assert str(error.value) == "OpenAI request failed."
    assert error.value.__suppress_context__


def test_removed_provider_rejected():
    provider = "mock"
    with pytest.raises(MagiError):
        MagiConfig.from_dict({"models": {"compiler": {"provider": provider, "model": "test"}}})
    with pytest.raises(ValueError):
        JobManager._validate_request("Request", None, provider)


def test_demo_rejected_and_openai_default():
    with pytest.raises(ValueError):
        JobManager._validate_request("Request", True, None)
    assert JobManager._validate_request("Request", None, None) == "openai"
