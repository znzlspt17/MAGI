"""모델 호출과 이력 경계의 사용자 전용 요약 계약."""
from copy import deepcopy
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

    def usage(self):
        return deepcopy(self.data)

    def save_usage(self, value):
        self.data = deepcopy(value)


class Provider:
    provider_name = "openai"


def test_call_observation_and_history_freeze():
    documents = Documents()
    data = {"nodes": [], "executions": []}
    history = ExecutionHistory(documents)
    history._load = lambda **kwargs: deepcopy(data)
    history._save = lambda saved: (data.clear(), data.update(saved))
    history.stage("run", "spec_compile", "started")
    call = CallUsage(documents, Provider(), "gpt-6-luna", "spec_compile")
    call.succeeded(CompletionResult(text="", input_tokens=12, output_tokens=4, reasoning_tokens=0,
                                    reasoning_summary="검토 요약"))
    history.stage("run", "spec_compile", "completed")
    node = data["nodes"][0]
    model_call = history.detail(node["id"])["model_calls"][0]
    assert model_call["reasoning_summary"] == "검토 요약"
    assert model_call["reasoning_tokens"] == 0
    assert model_call["request_settings"]["verbosity"] == "high"
    assert model_call["attempt"] == 1 and model_call["status"] == "success"
    later = CallUsage(documents, Provider(), "gpt-6-luna", "interview")
    later.succeeded(CompletionResult(text="", reasoning_summary="다른 단계"))
    assert len(history.detail(node["id"])["model_calls"]) == 1
    assert "model_calls" not in history.graph()["nodes"][0]


def test_old_history_does_not_fabricate_model_calls():
    data = {"nodes": [{"id": "old", "stage": "interview", "status": "completed"}], "executions": []}
    history = ExecutionHistory(None)
    history._load = lambda **kwargs: deepcopy(data)
    assert "model_calls" not in history.detail("old")


def test_malformed_stored_model_call_does_not_break_detail():
    bad = {"id": "a" * 32, "stage": "interview", "attempt": 1, "status": [],
           "request_settings": {"reasoning": {"mode": []}, "verbosity": [], "max_output_tokens": 3}}
    data = {"nodes": [{"id": "old", "stage": "interview", "status": "completed", "model_calls": [bad]}], "executions": []}
    history = ExecutionHistory(None)
    history._load = lambda **kwargs: deepcopy(data)
    assert history.detail("old")["model_calls"] == []


def test_retry_freezes_only_own_execution_and_never_exposes_extra_fields(capsys):
    from backend.infrastructure.progress_store import projection

    documents = Documents()
    data = {"nodes": [], "executions": []}
    history = ExecutionHistory(documents)
    history._load = lambda **kwargs: deepcopy(data)
    history._save = lambda saved: (data.clear(), data.update(saved))
    history.stage("run", "spec_compile", "started")
    first = CallUsage(documents, Provider(), "gpt-6-luna", "spec_compile")
    first.record_failed_completion(CompletionResult(text="", reasoning_summary="private-retry"))
    first.failed()
    documents.runtime.job["execution_id"] = "other-run"
    other = CallUsage(documents, Provider(), "gpt-6-luna", "spec_compile")
    other.succeeded(CompletionResult(text="", reasoning_summary="other-summary"))
    documents.runtime.job["execution_id"] = "run"
    final = CallUsage(documents, Provider(), "gpt-6-luna", "spec_compile")
    final.succeeded(CompletionResult(text="", reasoning_summary="private-success"))
    documents.data["attempts"][-1]["extra_untrusted"] = "do-not-expose"
    history.stage("run", "spec_compile", "completed")
    node = data["nodes"][0]
    calls = history.detail(node["id"])["model_calls"]
    assert [item["attempt"] for item in calls] == [1, 2]
    assert [item["status"] for item in calls] == ["failed", "success"]
    assert [item["reasoning_summary"] for item in calls] == ["private-retry", "private-success"]
    assert "extra_untrusted" not in repr(calls) and "other-summary" not in repr(calls)
    assert "private-success" not in repr(projection({}, [node]))
    assert "private-success" not in capsys.readouterr().out


def test_completed_tool_outputs_are_not_resent_after_downstream_failure(monkeypatch):
    from contextlib import contextmanager, nullcontext
    from pydantic import BaseModel
    from backend.infrastructure.provider_call import _complete_once

    class Final(BaseModel):
        answer: str

    class Writer(Documents):
        store = SimpleNamespace(transaction=lambda: nullcontext())

        def __init__(self):
            super().__init__()
            self.saved = {}

        def exists(self, path):
            return path in self.saved

        def read_json(self, path):
            return deepcopy(self.saved[path])

        def write_json(self, path, data):
            self.saved[path] = deepcopy(data)

    class FakeProvider(Provider):
        def __init__(self):
            self.messages = []

        def complete_result(self, messages, **kwargs):
            self.messages.append(deepcopy(messages))
            if len(self.messages) == 1:
                from backend.errors import Error
                error = Error("invalid structured output")
                error.completion = CompletionResult(text="", response_id="resp_test")
                raise error
            return CompletionResult(text="", parsed=Final(answer="ok"), response_id="resp_test")

    @contextmanager
    def conversation(writer, provider):
        yield "conv_test"

    monkeypatch.setattr("backend.infrastructure.provider_call.job_conversation", conversation)
    monkeypatch.setattr("backend.infrastructure.provider_call.call_started", lambda *args: None)
    monkeypatch.setattr("backend.infrastructure.provider_call.call_finished", lambda *args: None)
    writer, provider = Writer(), FakeProvider()
    kwargs = dict(model="gpt-6-luna", stage="interview", isolated_schema=Final,
                  tools=[], tool_choice="none", return_completion=True,
                  tool_result=[{"call_id": "opaqueToolCall42", "content": "safe result"}])
    with pytest.raises(Exception, match="invalid structured output"):
        _complete_once(writer, provider, [{"role": "user", "content": "request"}], **kwargs)
    _complete_once(writer, provider, [{"role": "user", "content": "request"}], **kwargs)
    assert [item["role"] for item in provider.messages[0]] == ["tool", "user"]
    assert [item["role"] for item in provider.messages[1]] == ["user"]
