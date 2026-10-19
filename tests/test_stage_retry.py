"""단계별 공통 재시도 예산, 보정 메시지, 공개 이력을 검증한다."""

import json

import pytest

from backend.infrastructure.stage_retry import CURRENT_RETRY, current_messages, attempt_limit
from backend.infrastructure.output_language import OutputLanguageError
from backend.pipeline.builder import _stage


@pytest.mark.parametrize("success", [True, False])
def test_stage_retry_budget_and_input_isolation(success):
    events, calls = [], []
    original = {"answers": ["사용자 결정"]}

    def node(state):
        calls.append(CURRENT_RETRY.get()["attempt"])
        assert state == original
        state["answers"].append("실패한 변경")
        assert attempt_limit() == 1
        if success and len(calls) == 4:
            return {"status": "done"}
        raise OutputLanguageError(["request_summary: ko"])

    wrapped = _stage("interview", node, events.append)
    if success:
        assert wrapped(original) == {"status": "done"}
    else:
        with pytest.raises(OutputLanguageError):
            wrapped(original)
    assert calls == [0, 1, 2, 3]
    assert original == {"answers": ["사용자 결정"]}
    assert CURRENT_RETRY.get() is None
    assert [e["result"]["summary"] for e in events if e["state"] == "retrying"] == [
        f"재시도 중… ({n}/3)" for n in range(1, 4)]
    assert events[-1]["state"] == ("completed" if success else "failed")


def test_retry_preserves_inputs_and_passes_only_validation_metadata():
    original = [{"role": "system", "content": "Original schema"}, {"role": "user", "content": "Original request and decisions"}]
    error = OutputLanguageError(["assumptions[0]: ko"])
    token = CURRENT_RETRY.set({"attempt": 2, "error": error})
    try:
        messages = current_messages(original, "interview")
    finally:
        CURRENT_RETRY.reset(token)
    assert messages[:-1] == original
    metadata = json.loads(messages[-1]["content"].split("\n", 1)[1])
    assert metadata["retry_attempt"] == 2
    assert metadata["max_retries"] == 3
    assert metadata["validation_failures"] == ["assumptions[0]: ko"]
    assert "Korean" in metadata["language_rules"]
    assert len(original) == 2


def test_job_progress_publishes_retry_message(tmp_path, monkeypatch):
    from backend.server.job_manager import JobManager

    snapshots = []
    manager = JobManager(tmp_path, on_change=snapshots.append)
    monkeypatch.setattr(manager, "_submit_locked", lambda *args: None)
    try:
        job = manager.create("로컬 메모 앱")
        manager._engine_progress(job["id"], {"stage": "interview", "state": "started"})
        for n in range(1, 4):
            manager._engine_progress(job["id"], {"stage": "interview", "state": "retrying", "result": {"retry_attempt": n}})
            assert snapshots[-1]["event"] == "job.changed"
            public = manager.public(job["id"])
            assert public["message"] == f"재시도 중… ({n}/3)"
            assert public["progress"]["retry_attempt"] == n
            graph = public["execution_graph"]
            assert graph["nodes"][-1]["summary"] == f"재시도 중… ({n}/3)"
    finally:
        manager.close()


def test_pipeline_language_and_source_failures_share_four_provider_calls(tmp_path):
    import httpx2
    from backend.infrastructure.artifact_writer import ArtifactWriter
    from backend.infrastructure.provider_call import complete_with_usage
    from backend.providers.llm_provider import OpenAIProvider
    from backend.services.requirement_lock_builder import RequirementLockBuilder
    from backend.models import InterviewResult, QAItem
    from test_conversation_structured import packet, transport
    from test_output_language import lock_value

    requests, events = [], []
    latest = {}
    writer = ArtifactWriter(tmp_path)
    provider = OpenAIProvider(api_key="fake-test-value")

    def handle(request):
        requests.append(json.loads(request.content))
        from prompt_fixtures import model_context
        model_context(requests[-1]['input'], latest)
        value = lock_value()
        if len(requests) in {1, 3}:
            value["request_summary"] = "Wrong language"
        elif len(requests) == 2:
            value["mandatory_requirements"][0]["source"] = "user_request"
        from prompt_fixtures import short_sources
        return httpx2.Response(200, json=packet(short_sources(value, latest), f"resp_{len(requests)}"))

    def complete(messages):
        return complete_with_usage(writer, provider, messages, model="gpt-6-luna", stage="requirement_lock")

    def node(state):
        sheet = RequirementLockBuilder().build(state, {}, InterviewResult("feature", [], [],
            pre_answers=[QAItem("PLATFORM-001", "대상?", "Windows")]), provider_messages_fn=complete)
        return {"status": "ANALYZING", "request_summary": sheet.request_summary}

    with transport(handle):
        result = _stage("requirement_lock", node, events.append)({"user_request": "메모 앱", "confirmed_user_sources": {'user_answer:PLATFORM-001': 'Windows'}})
    assert result["request_summary"] == "로컬 메모 앱"
    assert len(requests) == 4
    assert len({request["conversation"] for request in requests}) == 1
    for n, request in enumerate(requests[1:], 1):
        retry = next(item["content"] for item in request["input"]
                     if isinstance(item["content"], str) and item["content"].startswith("Stage retry context:"))
        assert json.loads(retry.split("\n", 1)[1])["retry_attempt"] == n
    assert [e["state"] for e in events] == ["started", "retrying", "retrying", "retrying", "completed"]
