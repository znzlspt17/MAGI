"""원격 통신 없이 작업 대화의 수명주기·호출 계약·중복 보호를 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest
from pydantic import BaseModel

from backend.errors import Error, InvalidStateError
from backend.infrastructure.conversation_state import (
    cache_key, call_finished, call_started, job_conversation,
)
from backend.infrastructure.provider_call import _complete_once
from backend.infrastructure.workflow_store import CURRENT_ATTEMPT, TaskJournal
from backend.knowledge.core import Documents
from backend.models import CompletionResult
from backend.model_policy import MODEL
from backend.providers.llm_provider import ChatModelProvider
from chat_model_fixture import transport
from test_models import response


class Output(BaseModel):
    value: str


def documents(store, ident="job-a"):
    project = store.create_project("대화 테스트")
    store.save_job({"id": ident, "project_id": project["id"], "request": "보존할 원본"})
    return Documents(store, ident)


def provider():
    return SimpleNamespace(
        provider_name="openai", create_conversation=Mock(return_value="conv_test"),
        initialize_conversation=Mock(),
        complete_result=Mock(return_value=CompletionResult(text="", parsed=Output(value="ok"), response_id="resp_test")),
    )


def saved(store, ident="job-a"):
    with store.transaction(mode="read") as conn:
        return conn.execute("SELECT openai_conversation_id,openai_conversation_state,openai_call_pending,"
                            "openai_last_response_id FROM jobs WHERE id=%s", (ident,)).fetchone()


def test_http_initialization_and_followup_preserve_boundaries_and_delta():
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path == "/v1/conversations":
            payload = {"id": "conv_test", "object": "conversation", "created_at": 1, "metadata": {}}
        elif request.url.path.endswith("/items"):
            payload = {"object": "list", "data": [], "has_more": False}
        else:
            payload = response()
        return httpx2.Response(200, json=payload, request=request)

    from backend.infrastructure.conversation_state import cache_block
    bootstrap = [{"role": "developer", "content": [cache_block("fixed policy")]},
                 {"role": "user", "content": [cache_block("original request")]}]
    with transport(handle):
        client = ChatModelProvider(api_key="fake-test-value")
        ident = client.create_conversation()
        client.initialize_conversation(ident, bootstrap)
        for stage in ("interview", "spec_translation"):
            client.complete_result([
                {"role": "user", "content": "Original user request (immutable):\noriginal request"},
                {"role": "assistant", "content": "do not replay"},
                {"role": "user", "content": "new input"},
            ], model=MODEL, conversation_id=ident, instructions=stage, cache_key=cache_key("job-a"))
    assert requests[1][1]["items"] == bootstrap
    for _, body in requests[2:]:
        assert body["conversation"] == ident
        assert "previous_response_id" not in body and "instructions" not in body
        assert body["prompt_cache_options"] == {"mode": "implicit", "ttl": "30m"}
        assert [item["role"] for item in body["input"]] == ["developer", "user"]
        assert "do not replay" not in json.dumps(body) and "original request" not in json.dumps(body)
    assert requests[2][1]["prompt_cache_key"] == requests[3][1]["prompt_cache_key"]
    assert cache_key("job-a") != cache_key("job-b")


def test_existing_job_bootstrap_and_restart_do_not_recreate_or_replay(store):
    docs, client = documents(store), provider()
    docs.state = {"requirement_lock_sheet": {"decisions": ["현재 확정"]}, "review_questions": ["미해결"]}
    docs.write_text("draft/approval_candidate_spec.en.md", "current specification")
    with job_conversation(docs, client) as ident:
        assert saved(store)["openai_conversation_state"] == "ready"
        call_started(docs, client)
        call_finished(docs, client, CompletionResult(text="ok", response_id="resp_first"))
    initial = json.dumps(client.initialize_conversation.call_args.args[1], ensure_ascii=False)
    assert all(value in initial for value in ("보존할 원본", "현재 확정", "미해결", "current specification"))
    store.save_job({"id": docs.job_id, "project_id": store.jobs()[0]["project_id"], "request": "changed metadata"})
    with job_conversation(Documents(store, docs.job_id), client) as resumed:
        assert resumed == ident
    client.create_conversation.assert_called_once()
    client.initialize_conversation.assert_called_once()
    assert saved(store)["openai_last_response_id"] == "resp_first"


@pytest.mark.parametrize("failure", ["create", "initialize", "save_id"])
def test_uncertain_initialization_never_repeats_automatically(store, monkeypatch, failure):
    docs, client = documents(store), provider()
    if failure == "create":
        client.create_conversation.side_effect = Error("safe create failure")
    elif failure == "initialize":
        client.initialize_conversation.side_effect = Error("safe initialize failure")
    else:
        transaction = store.transaction

        @contextmanager
        def fail_save(**kwargs):
            with transaction(**kwargs) as conn:
                if saved_state[0]:
                    raise ValueError("safe database failure")
                yield conn

        saved_state = [False]
        client.create_conversation.side_effect = lambda: (saved_state.__setitem__(0, True) or "conv_test")
        monkeypatch.setattr(store, "transaction", fail_save)
    with pytest.raises((Error, ValueError)):
        with job_conversation(docs, client):
            pytest.fail("초기화 실패 후 호출하면 안 된다")
    if failure == "save_id":
        monkeypatch.setattr(store, "transaction", transaction)
    with pytest.raises(InvalidStateError, match="초기화"):
        with job_conversation(docs, client):
            pytest.fail("초기화를 자동 반복하면 안 된다")
    client.create_conversation.assert_called_once()
    client.complete_result.assert_not_called()


def test_all_schema_paths_share_conversation_and_explicit_stage_contract(store):
    docs, client = documents(store), provider()
    stages = ("planner", "interview", "requirement_lock", "spec_compile", "checklist_critic",
              "review_resolution", "change_review", "impact_review", "spec_translation")
    for stage in stages:
        assert _complete_once(docs, client, [{"role": "system", "content": "stage policy"},
                                            {"role": "user", "content": "current evidence"}],
                              model=MODEL, stage=stage, isolated_schema=Output).value == "ok"
    assert {call.kwargs["conversation_id"] for call in client.complete_result.call_args_list} == {"conv_test"}
    assert len({call.kwargs["cache_key"] for call in client.complete_result.call_args_list}) == 1
    for stage, call in zip(stages, client.complete_result.call_args_list):
        assert f"Current stage: {stage}." in call.kwargs["instructions"]
        assert "older outputs" in call.kwargs["instructions"]


def test_uncertain_call_blocks_until_explicit_replay_and_records_response(store):
    docs, client = documents(store), provider()
    with job_conversation(docs, client):
        call_started(docs, client)
    with pytest.raises(InvalidStateError, match="호출 반복"):
        with job_conversation(docs, client):
            pytest.fail("불확실한 호출을 반복하면 안 된다")
    journal = TaskJournal(store.connect(), docs.job_id)
    journal.conn.execute("SET search_path TO workflow, public")
    journal.begin("task")
    token = CURRENT_ATTEMPT.set({"allow_replay": True, "journal": journal, "task_id": "task"})
    try:
        with job_conversation(docs, client):
            call_finished(docs, client, CompletionResult(text="ok", response_id="resp_replayed"))
        assert CURRENT_ATTEMPT.get()["allow_replay"] is False
        row = journal.conn.execute("SELECT payload FROM workflow_task_results WHERE thread_id=%s", (docs.job_id,)).fetchone()
        assert json.loads(row["payload"])["response_ids"] == ["resp_replayed"]
    finally:
        CURRENT_ATTEMPT.reset(token)
        journal.conn.close()
    assert saved(store)["openai_call_pending"] is False
    client.create_conversation.assert_called_once()


def test_response_failure_keeps_same_conversation_and_no_automatic_retry(store):
    docs, client = documents(store), provider()
    client.complete_result.side_effect = Error("safe transport failure")
    arguments = dict(model=MODEL, stage="planner", isolated_schema=Output)
    with pytest.raises(Error):
        _complete_once(docs, client, [], **arguments)
    with pytest.raises(InvalidStateError, match="호출 반복"):
        _complete_once(docs, client, [], **arguments)
    client.complete_result.assert_called_once()
    assert saved(store)["openai_call_pending"] is True
    client.create_conversation.assert_called_once()


def test_received_invalid_result_can_be_corrected_in_same_conversation(store):
    docs, client = documents(store), provider()
    error = Error("safe validation failure")
    error.completion = CompletionResult(text="", response_id="resp_invalid")
    client.complete_result.side_effect = [error, CompletionResult(text="", parsed=Output(value="fixed"), response_id="resp_fixed")]
    arguments = dict(model=MODEL, stage="spec_compile", isolated_schema=Output)
    with pytest.raises(Error):
        _complete_once(docs, client, [], **arguments)
    assert saved(store)["openai_call_pending"] is False
    assert _complete_once(docs, client, [{"role": "user", "content": "validation correction"}], **arguments).value == "fixed"
    assert {call.kwargs["conversation_id"] for call in client.complete_result.call_args_list} == {"conv_test"}
    client.create_conversation.assert_called_once()


def test_budget_failure_before_http_does_not_mark_remote_call_uncertain(store):
    docs, fake = documents(store), provider()
    with job_conversation(docs, fake):
        pass
    meter = Mock()
    meter.reserve.side_effect = Error("safe budget failure")
    client = ChatModelProvider(api_key="fake-test-value", meter=meter)
    with transport(Mock(side_effect=AssertionError("예산 예약 실패 뒤 HTTP 요청 금지"))), pytest.raises(Error, match="budget"):
        _complete_once(docs, client, [], model=MODEL, stage="planner", isolated_schema=Output)
    assert saved(store)["openai_call_pending"] is False


@pytest.mark.parametrize("status,code,expected", [
    (404, "not_found", "접근할 수 없습니다"),
    (400, "context_length_exceeded", "문맥 한도"),
])
def test_http_permanent_failures_have_safe_specific_diagnostics(status, code, expected):
    def handle(request):
        return httpx2.Response(status, json={"error": {"code": code, "message": "DO_NOT_PROPAGATE", "type": "invalid_request_error"}}, request=request)
    with transport(handle), pytest.raises(Error) as caught:
        ChatModelProvider(api_key="fake-test-value").complete_result(
            [{"role": "user", "content": "input"}], model=MODEL, conversation_id="conv_test")
    assert expected in str(caught.value) and "DO_NOT_PROPAGATE" not in str(caught.value)
    from backend.server.diagnostics import diagnose_exception
    assert expected in diagnose_exception(caught.value)["reason"]


def test_parallel_same_job_initializes_once_and_separate_jobs_are_isolated(store):
    docs, client = documents(store), provider()
    active = []

    def run(_):
        with job_conversation(docs, client) as ident:
            assert not active
            active.append(ident)
            call_started(docs, client)
            call_finished(docs, client, CompletionResult(text="ok", response_id="resp_parallel"))
            active.pop()
        return ident

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, range(2))) == ["conv_test", "conv_test"]
    client.create_conversation.assert_called_once()
    other = documents(store, "job-b")
    other_client = provider()
    other_client.create_conversation.return_value = "conv_other"
    with job_conversation(other, other_client) as ident:
        assert ident != saved(store)["openai_conversation_id"]
