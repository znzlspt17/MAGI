"""모델 호출과 이력 경계의 사용자 전용 요약 계약."""
from copy import deepcopy
from unittest.mock import AsyncMock
from tests.backend.application.async_helpers import run_async
from types import SimpleNamespace
import pytest

from backend.application.execution_history import ExecutionHistory
from backend.infrastructure.call_usage import CallUsage
from backend.models import CompletionResult


class Documents:
    job_id = "job"

    def __init__(self):
        self.data = {"attempts": []}
        self.runtime = SimpleNamespace(job={"execution_id": "run"}, meter=None)

    async def usage(self):
        return deepcopy(self.data)

    async def save_usage(self, value):
        self.data = deepcopy(value)


class Provider:
    provider_name = "openai"


@run_async
async def test_call_observation_and_history_freeze():
    documents = Documents()
    data = {"nodes": [], "executions": []}
    history = ExecutionHistory(documents)
    history._load = AsyncMock(side_effect=lambda **kwargs: deepcopy(data))
    history._save = AsyncMock(side_effect=lambda saved: (data.clear(), data.update(saved)))
    (await history.stage("run", "spec_compile", "started"))
    call = (await CallUsage.create(documents, Provider(), "gpt-6-luna", "spec_compile"))
    (await call.succeeded(CompletionResult(text="", input_tokens=12, output_tokens=4, reasoning_tokens=0,
                                    reasoning_summary="검토 요약")))
    (await history.stage("run", "spec_compile", "completed"))
    node = data["nodes"][0]
    model_call = (await history.detail(node["id"]))["model_calls"][0]
    assert model_call["reasoning_summary"] == "검토 요약"
    assert model_call["reasoning_tokens"] == 0
    assert model_call["request_settings"]["verbosity"] == "high"
    assert model_call["attempt"] == 1 and model_call["status"] == "success"
    later = (await CallUsage.create(documents, Provider(), "gpt-6-luna", "interview"))
    (await later.succeeded(CompletionResult(text="", reasoning_summary="다른 단계")))
    assert len((await history.detail(node["id"]))["model_calls"]) == 1
    assert "model_calls" not in (await history.graph())["nodes"][0]


@run_async
async def test_old_history_does_not_fabricate_model_calls():
    data = {"nodes": [{"id": "old", "stage": "interview", "status": "completed"}], "executions": []}
    history = ExecutionHistory(None)
    history._load = AsyncMock(side_effect=lambda **kwargs: deepcopy(data))
    assert "model_calls" not in (await history.detail("old"))


@run_async
async def test_malformed_stored_model_call_does_not_break_detail():
    bad = {"id": "a" * 32, "stage": "interview", "attempt": 1, "status": [],
           "request_settings": {"reasoning": {"mode": []}, "verbosity": [], "max_output_tokens": 3}}
    data = {"nodes": [{"id": "old", "stage": "interview", "status": "completed", "model_calls": [bad]}], "executions": []}
    history = ExecutionHistory(None)
    history._load = AsyncMock(side_effect=lambda **kwargs: deepcopy(data))
    assert (await history.detail("old"))["model_calls"] == []


@run_async
async def test_retry_freezes_only_own_execution_and_never_exposes_extra_fields(capsys):
    from backend.infrastructure.progress_store import projection

    documents = Documents()
    data = {"nodes": [], "executions": []}
    history = ExecutionHistory(documents)
    history._load = AsyncMock(side_effect=lambda **kwargs: deepcopy(data))
    history._save = AsyncMock(side_effect=lambda saved: (data.clear(), data.update(saved)))
    (await history.stage("run", "spec_compile", "started"))
    first = (await CallUsage.create(documents, Provider(), "gpt-6-luna", "spec_compile"))
    first.record_failed_completion(CompletionResult(text="", reasoning_summary="private-retry"))
    (await first.failed())
    documents.runtime.job["execution_id"] = "other-run"
    other = (await CallUsage.create(documents, Provider(), "gpt-6-luna", "spec_compile"))
    (await other.succeeded(CompletionResult(text="", reasoning_summary="other-summary")))
    documents.runtime.job["execution_id"] = "run"
    final = (await CallUsage.create(documents, Provider(), "gpt-6-luna", "spec_compile"))
    (await final.succeeded(CompletionResult(text="", reasoning_summary="private-success")))
    documents.data["attempts"][-1]["extra_untrusted"] = "do-not-expose"
    (await history.stage("run", "spec_compile", "completed"))
    node = data["nodes"][0]
    calls = (await history.detail(node["id"]))["model_calls"]
    assert [item["attempt"] for item in calls] == [1, 2]
    assert [item["status"] for item in calls] == ["failed", "success"]
    assert [item["reasoning_summary"] for item in calls] == ["private-retry", "private-success"]
    assert "extra_untrusted" not in repr(calls) and "other-summary" not in repr(calls)
    assert "private-success" not in repr(projection({}, [node]))
    assert "private-success" not in capsys.readouterr().out


@run_async
async def test_completed_tool_outputs_are_not_resent_after_downstream_failure(monkeypatch):
    from contextlib import asynccontextmanager, nullcontext
    from pydantic import BaseModel
    from backend.infrastructure.provider_call import _complete_once

    class Final(BaseModel):
        answer: str

    class Writer(Documents):
        store = SimpleNamespace(transaction=lambda: nullcontext())

        def __init__(self):
            super().__init__()
            self.saved = {}

        async def exists(self, path):
            return path in self.saved

        async def read_json(self, path):
            return deepcopy(self.saved[path])

        async def write_json(self, path, data):
            self.saved[path] = deepcopy(data)

    class FakeProvider(Provider):
        def __init__(self):
            self.messages = []

        async def complete_result(self, messages, **kwargs):
            self.messages.append(deepcopy(messages))
            if len(self.messages) == 1:
                from backend.errors import Error
                error = Error("invalid structured output")
                error.completion = CompletionResult(text="", response_id="resp_test")
                raise error
            return CompletionResult(text="", parsed=Final(answer="ok"), response_id="resp_test")

    @asynccontextmanager
    async def conversation(writer, provider):
        yield "conv_test"

    monkeypatch.setattr("backend.infrastructure.provider_call.job_conversation", conversation)
    monkeypatch.setattr("backend.infrastructure.provider_call.call_started", AsyncMock())
    monkeypatch.setattr("backend.infrastructure.provider_call.call_finished", AsyncMock())
    writer, provider = Writer(), FakeProvider()
    kwargs = dict(model="gpt-6-luna", stage="interview", isolated_schema=Final,
                  tools=[], tool_choice="none", return_completion=True,
                  tool_result=[{"call_id": "opaqueToolCall42", "content": "safe result"}])
    with pytest.raises(Exception, match="invalid structured output"):
        (await _complete_once(writer, provider, [{"role": "user", "content": "request"}], **kwargs))
    (await _complete_once(writer, provider, [{"role": "user", "content": "request"}], **kwargs))
    assert [item["role"] for item in provider.messages[0]] == ["tool", "user"]
    assert [item["role"] for item in provider.messages[1]] == ["user"]
