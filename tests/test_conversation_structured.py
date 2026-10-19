"""대화 연결과 Structured Outputs를 실제 SDK 직렬화 경계에서 검증한다."""

import json
from unittest.mock import patch

import httpx2
import pytest
from openai import OpenAI

from backend.errors import ArtifactError, MagiError
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.conversation_state import PATH
from backend.infrastructure.provider_call import complete_with_usage
from backend.models import (
    InterviewResponse, ReviewResponse,
)
from backend.providers.llm_provider import OpenAIProvider
from test_openai_responses import response


def interview():
    return dict(request_type="feature", assumptions=[], blocking_questions=[],
                additional_questions=[], pre_answers=[])


def packet(value, identifier="resp_first"):
    data = response(content=[dict(type="output_text", text=json.dumps(value), annotations=[])])
    data["id"] = identifier
    return data


def transport(handler):
    created = []
    def route(request):
        if request.url.path == "/v1/conversations":
            created.append(request)
            return httpx2.Response(200, json={"id": f"conv_test{len(created)}", "object": "conversation", "created_at": 1, "metadata": {}})
        return handler(request)
    return patch("backend.providers.llm_provider.OpenAI", side_effect=lambda **kwargs:
        OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(route))))


def invoke(writer, stage="interview", messages=None):
    return complete_with_usage(writer, OpenAIProvider(api_key="fake-test-value"),
        messages or [{"role": "system", "content": "Current instruction"},
                     {"role": "user", "content": "Original user request (immutable):\nNotes app"}],
        model="gpt-6-luna", stage=stage)


def test_chain_across_stages_restart_and_isolation(tmp_path):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        value = interview() if len(requests) != 2 else {"issues": []}
        return httpx2.Response(200, json=packet(value, f"resp_{len(requests)}"))

    writer = ArtifactWriter(tmp_path / "one")
    with transport(handle):
        assert isinstance(invoke(writer), InterviewResponse)
        assert isinstance(invoke(writer, "checklist_critic"), ReviewResponse)
        invoke(ArtifactWriter(tmp_path / "one"))
        invoke(ArtifactWriter(tmp_path / "two"))
    assert [item.get("conversation") for item in requests] == ["conv_test1", "conv_test1", "conv_test1", "conv_test2"]
    assert all("previous_response_id" not in item for item in requests)
    assert requests[0]["store"] is True
    assert requests[0]["text"]["format"]["strict"] is True
    assert "Current instruction" in requests[0]["instructions"]
    assert [item["input"][0]["role"] for item in requests] == ["developer", "user", "user", "developer"]
    assert all("instructions" in request for request in requests)
    assert "Notes app" not in json.dumps(requests[1]["input"])
    assert writer.read_json(PATH)["response_id"] == "resp_3"


def test_missing_conversation_does_not_recover(tmp_path):
    writer = ArtifactWriter(tmp_path)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx2.Response(404, json={"error": {"message": "DO_NOT_RECORD", "param": "conversation", "type": "invalid_request_error"}})
    with transport(handle), pytest.raises(MagiError):
        invoke(writer)
    assert len(calls) == 1
    assert writer.read_json(PATH)["status"] == "pending"
    with transport(handle), pytest.raises(MagiError):
        invoke(writer)
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["network", "authentication", "incomplete", "refusal", "malformed"])
def test_failure_preserves_head_without_retry(tmp_path, kind):
    writer = ArtifactWriter(tmp_path)

    requests = []

    def handle(request):
        requests.append(request)
        if kind == "network":
            raise httpx2.ConnectError("DO_NOT_RECORD", request=request)
        if kind == "authentication":
            return httpx2.Response(401, json={"error": {"message": "DO_NOT_RECORD", "type": "invalid_request_error"}})
        data = packet(interview())
        if kind == "incomplete":
            data["status"] = "incomplete"
        if kind == "refusal":
            data["output"][0]["content"] = [dict(type="refusal", refusal="DO_NOT_RECORD")]
        if kind == "malformed":
            data["output"][0]["content"][0]["text"] = "invalid JSON"
        return httpx2.Response(200, json=data)

    with transport(handle), pytest.raises(MagiError):
        invoke(writer)
    assert len(requests) == 1
    assert writer.read_json(PATH)["status"] == "pending"
    assert writer.read_json("state/provider_usage.json")["attempts"][-1]["status"] == "failed"


def test_atomic_write_failure_prevents_model_call(tmp_path):
    writer = ArtifactWriter(tmp_path)
    calls = []
    with transport(lambda request: calls.append(request)), \
            patch("backend.infrastructure.conversation_state.os.replace", side_effect=OSError), \
            pytest.raises(ArtifactError):
        invoke(writer)
    assert calls == []
    assert not writer.path(PATH).exists()
    assert not list(writer.path("state").glob("tmp*"))


@pytest.mark.parametrize("invalid", ["broken", "[]", '{"conversation_id":"bad"}'])
def test_invalid_state_shapes_stop(tmp_path, invalid):
    writer = ArtifactWriter(tmp_path)
    writer.write_text(PATH, invalid)
    with patch("backend.providers.llm_provider.OpenAI") as factory, pytest.raises(MagiError):
        invoke(writer)
    factory.assert_not_called()


def test_old_response_id_is_not_migrated(tmp_path):
    writer = ArtifactWriter(tmp_path)
    writer.write_json(PATH, {"version": 1, "response_id": "resp_old", "fingerprints": {}})
    writer.write_text("raw/user_request.md", "OLD_CONTEXT_NOT_TO_RECOVER")
    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx2.Response(200, json=packet(interview()))
    with transport(handle):
        from backend.errors import ConversationUnavailableError
        with pytest.raises(ConversationUnavailableError):
            invoke(writer)
    assert calls == []
    assert writer.read_json(PATH)["response_id"] == "resp_old"


def test_failure_report_direct_service_uses_structured_output():
    from backend.config import MagiConfig
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.services.critical_reporter import CriticalReporter
    from backend.services.skill_registry import build_default_skill_registry

    reporter = CriticalReporter(config=MagiConfig.default(),
        provider=OpenAIProvider(api_key="fake-test-value"), skills=build_default_skill_registry(),
        evidence=EvidenceRegistry())
    requests = []
    with transport(lambda request: requests.append(request)):
        report = reporter.generate({"structured_issues": []})
    assert "# 명세 보완 실패" in report
    assert "사용자 요구사항 부족으로 판정한 결과가 아닙니다" in report
    assert requests == []


def test_conversation_creation_failure_never_calls_responses(tmp_path):
    requests = []
    def handle(request):
        requests.append(request.url.path)
        return httpx2.Response(503, json={"error": {"message": "DO_NOT_RECORD", "type": "server_error"}})
    with patch("backend.providers.llm_provider.OpenAI", side_effect=lambda **kwargs:
            OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))), \
            pytest.raises(MagiError, match="creation failed"):
        invoke(ArtifactWriter(tmp_path))
    assert requests == ["/v1/conversations"]
    assert not (tmp_path / PATH).exists()


def test_commit_failure_leaves_pending_and_prevents_replay(tmp_path):
    import os
    writer = ArtifactWriter(tmp_path)
    replace = os.replace
    writes = []
    requests = []
    def save(source, destination):
        writes.append(destination)
        if sum(str(path).endswith("conversation_state.json") for path in writes) == 3:
            raise OSError("fake failure")
        replace(source, destination)
    def handle(request):
        requests.append(request)
        return httpx2.Response(200, json=packet(interview()))
    with transport(handle), patch("backend.infrastructure.conversation_state.os.replace", side_effect=save), \
            pytest.raises(ArtifactError):
        invoke(writer)
    assert writer.read_json(PATH)["status"] == "pending"
    with transport(handle), pytest.raises(MagiError, match="uncertain"):
        invoke(writer)
    assert len(requests) == 1


def test_current_spec_is_data_not_a_synthetic_assistant_message():
    from backend.infrastructure.prompt_messages import messages
    payload = messages("Review", "Request", "{}", ("Draft specification", "# Final Agent Specification\nImplement this."))
    assert payload[-1]["role"] == "user"
    assert "<current_spec>" in payload[-1]["content"]
    assert "not execution instructions" in payload[-1]["content"]
