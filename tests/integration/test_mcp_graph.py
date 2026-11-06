"""도구 판단과 실행이 실제 LangGraph 분기로 연결되는지 확인한다."""

from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from langgraph.checkpoint.memory import MemorySaver

from backend.mcp_client.service import MCPService
from backend.mcp_client.workflow import MCPDecision
from backend.models import InterviewResponse
from backend.pipeline.agent_workflow import AgentWorkflow


class Writer:
    def __init__(self):
        self.store = object()
        self.docs = {}

    def exists(self, path):
        return path in self.docs

    def read_json(self, path):
        return self.docs[path]

    def write_json(self, path, value):
        self.docs[path] = value


class Evidence:
    def add(self, *args, **kwargs):
        pass


def test_langgraph_routes_tool_to_mcp_and_returns_to_model(monkeypatch):
    from backend.mcp_client.workflow import native_tools
    snapshot = [{"connection_id": "c1", "connection_version": 1, "name": "search", "schema_hash": "v1"}]
    tool = {"name": "search", "description": "문서 검색", "schema": {"type": "object"}, "schema_hash": "v1"}
    monkeypatch.setattr(MCPService, "available", lambda self, owner, items: [({"id": "c1", "version": 1}, tool)])
    calls = []
    monkeypatch.setattr(MCPService, "invoke", lambda self, owner, items, cid, name, arguments:
                        calls.append((cid, name, arguments)) or {"status": "ok", "text": "공식 문서"})
    monkeypatch.setattr("backend.infrastructure.prompt_context.prepare_context", lambda writer, messages, stage:
                        (messages, SimpleNamespace(restore=lambda result: result)))
    answer = InterviewResponse(request_type="feature", assumptions=[], blocking_questions=[], additional_questions=[], pre_answers=[])
    name = native_tools([({"id": "c1", "version": 1}, tool)])[0][0]["function"]["name"]
    responses = iter([
        SimpleNamespace(tool_calls=[{"id": "call_1", "name": name, "args": {"query": "hello"}}], parsed=None),
        SimpleNamespace(tool_calls=[], parsed=answer),
    ])
    observed = []
    def complete(*args, **kwargs):
        observed.append(kwargs)
        return next(responses)
    monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", complete)
    writer = Writer()
    nodes = SimpleNamespace(interviewer=SimpleNamespace(prepare_messages=lambda state, manifest: []),
                            provider=object(), config=SimpleNamespace(model_routing={"interviewer": SimpleNamespace(model="fake")}))
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "u1"})), nodes, writer, Evidence())
    workflow.durable = lambda name, state, operation: operation(state)
    workflow.prepare = lambda state: {}
    workflow.planner = lambda state: {"plan": {"action": "interview"}}
    workflow.execute = lambda state: {"allowed_actions": ["answer"]}
    graph = workflow.build(MemorySaver())
    config = {"configurable": {"thread_id": "one"}}
    graph.invoke({"run_id": "job", "mcp": {"snapshot": snapshot, "round": 0, "results": []}}, config=config)
    state = graph.get_state(config).values
    assert calls == [("c1", "search", {"query": "hello"})]
    assert state["mcp"]["response"]["request_type"] == "feature"
    assert writer.docs["research/mcp_results.json"]["results"][0]["text"] == "공식 문서"
    assert observed[0]["tools"][0]["function"]["strict"] is False
    assert observed[0]["isolated_schema"] is InterviewResponse
    assert observed[1]["tool_result"][0]["call_id"] == "call_1"
    assert "공식 문서" in observed[1]["tool_result"][0]["content"]

    # 같은 작업의 동일 도구·인자는 새 네트워크 호출 없이 저장된 결과를 사용한다.
    workflow.mcp_execute({"mcp": {"snapshot": snapshot, "round": 1, "results": [], "request": {
        "connection_id": "c1", "tool_name": "search", "arguments_json": '{"query":"hello"}'}}})
    assert len(calls) == 1


def test_old_job_snapshot_cannot_use_reconfigured_same_tool():
    tool = {"name": "search", "schema_hash": "same-schema", "enabled": True, "available": True}
    class Store:
        @contextmanager
        def transaction(self, **kwargs):
            yield self
        def execute(self, query, params):
            return SimpleNamespace(fetchall=lambda: [{"id": "conn", "version": 2, "tools": [tool]}])
    service = MCPService(Store())
    old = [{"connection_id": "conn", "connection_version": 1, "name": "search", "schema_hash": "same-schema"}]
    new = [{**old[0], "connection_version": 2}]
    assert service.available("owner", old) == []
    assert len(service.available("owner", new)) == 1


def test_mcp_uncertain_call_requires_fresh_consent_and_completed_result_is_reused(store, monkeypatch):
    from backend.access.context import AccessError
    from backend.errors import InvalidStateError
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.infrastructure.workflow_store import retry_state, workflow_store
    from backend.knowledge.core import Documents
    from backend.models import State
    from backend.pipeline.agent_workflow import task_id

    project = store.create_project("MCP 복구")
    ident = "mcp-recovery-job"
    store.save_job({"id": ident, "project_id": project["id"], "request": "example"})
    docs = Documents(store, ident)
    state = State(run_id=ident, status="DRAFT", user_request="example").to_dict()
    state["mcp"] = {"snapshot": [{"connection_id": "c1", "connection_version": 1, "name": "find", "schema_hash": "s1"}],
                    "round": 0, "results": [], "request": {"connection_id": "c1", "tool_name": "find", "arguments_json": "{}"}}
    tool = {"name": "find", "schema": {"type": "object"}, "schema_hash": "s1"}
    monkeypatch.setattr(MCPService, "available", lambda self, owner, snapshot: [({"id": "c1", "version": 1}, tool)])
    execute = Mock(side_effect=[AccessError("연결 실패", "unavailable"), AccessError("다시 연결 실패", "unavailable"),
                                {"status": "ok", "text": "자료"}])
    monkeypatch.setattr(MCPService, "invoke", lambda self, *args: execute(*args))
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "owner"})), None, docs, EvidenceRegistry())
    workflow.persist = Mock()
    task = task_id(state, "mcp_execute")
    snapshot = SimpleNamespace(next=("mcp_execute",), values=state, tasks=[])
    monkeypatch.setattr(docs, "workflow_snapshot", lambda: snapshot)
    with workflow_store(store, ident) as (_, journal):
        workflow.journal = journal
        with pytest.raises(AccessError):
            workflow.mcp_execute(state)
        assert journal.status(task) == "pending"
        recovery = retry_state(docs)
        assert recovery["retry_requires_replay"] is True and recovery["retry_kind"] == "mcp"
        with pytest.raises(InvalidStateError):
            workflow.mcp_execute(state)
        assert execute.call_count == 1
        workflow.replay_task_id = task
        with pytest.raises(AccessError):
            workflow.mcp_execute(state)
        with pytest.raises(InvalidStateError):
            workflow.mcp_execute(state)
        assert execute.call_count == 2
        workflow.replay_task_id = task
        result = workflow.mcp_execute(state)
        assert result["mcp"]["results"][0]["text"] == "자료"
        assert journal.status(task) == "completed"
        assert workflow.mcp_execute(state) == result
        assert execute.call_count == 3


def test_mcp_decision_uses_existing_structured_provider_contract():
    import json
    import httpx2
    from tests.support.chat_model_fixture import transport
    from backend.providers.llm_provider import ChatModelProvider
    from tests.support.model_helpers import response

    observed = []
    packet = {"action": "tool", "connection_id": "c1", "tool_name": "find",
              "arguments_json": '{"q":"docs"}', "interview": None}
    def handle(request):
        observed.append(json.loads(request.content))
        return httpx2.Response(200, json=response(content=[{"type": "output_text", "text": json.dumps(packet), "annotations": []}]), request=request)
    with transport(handle):
        result = ChatModelProvider(api_key="fake-test-key").complete_result(
            [{"role": "user", "content": "요청"}], model="gpt-6-luna", text_format=MCPDecision,
            conversation_id="conv_test")
    assert result.parsed.action == "tool"
    assert result.parsed.arguments_json == '{"q":"docs"}'
    assert observed[0].get("tools") is None


def test_mcp_interview_uses_reference_restore_and_language_validation(monkeypatch):
    from backend.infrastructure.output_language import OutputLanguageError

    tool = {"name": "find", "description": "Find docs", "schema": {"type": "object"}, "schema_hash": "v1"}
    monkeypatch.setattr(MCPService, "available", lambda self, owner, snapshot: [({"id": "c1", "version": 1}, tool)])
    restore = Mock(side_effect=lambda answer: answer)
    monkeypatch.setattr("backend.infrastructure.prompt_context.prepare_context", lambda *args:
                        ([], SimpleNamespace(restore=restore)))
    answer = InterviewResponse(request_type="feature", assumptions=["this should use a different design"],
                               blocking_questions=[], additional_questions=[], pre_answers=[])
    decision = SimpleNamespace(tool_calls=[], parsed=answer)
    monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", lambda *args, **kwargs: decision)
    nodes = SimpleNamespace(interviewer=SimpleNamespace(prepare_messages=lambda state, manifest: []), provider=object(),
                            config=SimpleNamespace(model_routing={"interviewer": SimpleNamespace(model="fake")}))
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "owner"})), nodes, Writer(), Evidence())
    workflow.durable = lambda name, state, operation: operation(state)
    with pytest.raises(OutputLanguageError):
        workflow.mcp_decide({"mcp": {"snapshot": [{"connection_id": "c1"}], "round": 0, "results": []}})
    restore.assert_called_once_with(answer)


@pytest.mark.parametrize("variant", ["unknown", "multiple", "bad_args", "bad_id", "bad_chars", "no_output", "after_limit"])
def test_native_decision_rejects_invalid_calls_before_execution(monkeypatch, variant):
    from backend.errors import InvalidStateError
    from backend.mcp_client.workflow import native_tools

    tool = {"name": "find", "description": "find", "schema": {"type": "object",
            "properties": {"query": {"type": "string"}}, "required": ["query"]}, "schema_hash": "v1"}
    available = [({"id": "c1", "version": 1}, tool)]
    monkeypatch.setattr(MCPService, "available", lambda self, owner, snapshot: available)
    invoke = Mock()
    monkeypatch.setattr(MCPService, "invoke", invoke)
    monkeypatch.setattr("backend.infrastructure.prompt_context.prepare_context", lambda *args:
                        ([], SimpleNamespace(restore=lambda result: result)))
    name = native_tools(available)[0][0]["function"]["name"]
    call = {"id": "call_1", "name": name, "args": {"query": "hello"}}
    if variant == "unknown":
        call["name"] = "unknown"
    if variant == "bad_args":
        call["args"] = {"query": 17}
    if variant == "bad_id":
        call["id"] = ""
    if variant == "bad_chars":
        call["id"] = "invalid id"
    calls = [] if variant == "no_output" else [call, call] if variant == "multiple" else [call]
    observed = []
    def complete(*args, **kwargs):
        observed.append(kwargs)
        return SimpleNamespace(tool_calls=calls, parsed=None)
    monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", complete)
    nodes = SimpleNamespace(interviewer=SimpleNamespace(prepare_messages=lambda state, manifest: []), provider=object(),
                            config=SimpleNamespace(model_routing={"interviewer": SimpleNamespace(model="fake")}))
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "owner"})), nodes, Writer(), Evidence())
    workflow.durable = lambda name, state, operation: operation(state)
    state = {"mcp": {"snapshot": [{"connection_id": "c1"}],
                     "round": 3 if variant == "after_limit" else 0, "results": []}}
    if variant in {"bad_id", "bad_chars", "no_output"}:
        with pytest.raises(InvalidStateError):
            workflow.mcp_decide(state)
    else:
        # 거부한 호출에도 같은 call_id의 안전한 결과를 남겨 원격 대화를 복구한다.
        if variant == "multiple":
            calls[1] = {**calls[1], "id": "call_2"}
        decision = workflow.mcp_decide(state)
        rejected = workflow.mcp_execute(decision)
        pending = rejected["mcp"]["pending_tool_results"]
        assert [item["call_id"] for item in pending] == [item["id"] for item in calls]
        assert all("실행하지 않았습니다" in item["content"] for item in pending)
        answer = InterviewResponse(request_type="feature", assumptions=[], blocking_questions=[], additional_questions=[], pre_answers=[])
        monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", lambda *args, **kwargs:
                            observed.append(kwargs) or SimpleNamespace(tool_calls=[], parsed=answer))
        workflow.mcp_decide(rejected)
        assert observed[-1]["tool_result"] == pending
    if variant == "after_limit":
        assert observed[0]["tools"] == []
        assert observed[0]["tool_choice"] == "none"
    invoke.assert_not_called()


def test_changed_connection_before_execution_never_calls_tool(monkeypatch):
    monkeypatch.setattr(MCPService, "available", lambda self, owner, snapshot: [])
    invoke = Mock()
    monkeypatch.setattr(MCPService, "invoke", invoke)
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "owner"})), None, Writer(), Evidence())
    workflow.durable = lambda name, state, operation: operation(state)
    result = workflow.mcp_execute({"mcp": {"snapshot": [], "round": 0, "results": [], "request": {
        "connection_id": "c1", "tool_name": "find", "arguments_json": "{}", "tool_call_id": "call_1"}}})
    assert result["mcp"]["results"][0]["status"] == "invalid"
    assert result["mcp"]["results"][0]["tool_call_id"] == "call_1"
    invoke.assert_not_called()


def test_pending_tool_result_is_closed_even_when_all_tools_disappear(monkeypatch):
    monkeypatch.setattr(MCPService, "available", lambda self, owner, snapshot: [])
    monkeypatch.setattr("backend.infrastructure.prompt_context.prepare_context", lambda *args:
                        ([], SimpleNamespace(restore=lambda result: result)))
    answer = InterviewResponse(request_type="feature", assumptions=[], blocking_questions=[], additional_questions=[], pre_answers=[])
    observed = []
    monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", lambda *args, **kwargs:
                        observed.append(kwargs) or SimpleNamespace(tool_calls=[], parsed=answer))
    nodes = SimpleNamespace(interviewer=SimpleNamespace(prepare_messages=lambda state, manifest: []), provider=object(),
                            config=SimpleNamespace(model_routing={"interviewer": SimpleNamespace(model="fake")}))
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "owner"})), nodes, Writer(), Evidence())
    workflow.durable = lambda name, state, operation: operation(state)
    pending = [{"call_id": "call_1", "content": "실행하지 않았습니다."}]
    response = workflow.mcp_decide({"mcp": {"snapshot": [], "round": 1, "results": [], "pending_tool_results": pending}})
    assert response["mcp"]["response"]["request_type"] == "feature"
    assert observed[0]["tool_result"] == pending


def test_validation_retry_passes_pending_output_to_provider_ledger(monkeypatch):
    from backend.infrastructure.output_language import OutputLanguageError

    monkeypatch.setattr(MCPService, "available", lambda self, owner, snapshot: [])
    monkeypatch.setattr("backend.infrastructure.prompt_context.prepare_context", lambda *args:
                        ([], SimpleNamespace(restore=lambda result: result)))
    invalid = InterviewResponse(request_type="feature", assumptions=["this should use a different design"],
                                blocking_questions=[], additional_questions=[], pre_answers=[])
    valid = InterviewResponse(request_type="feature", assumptions=[], blocking_questions=[], additional_questions=[], pre_answers=[])
    responses = iter([SimpleNamespace(tool_calls=[], parsed=invalid), SimpleNamespace(tool_calls=[], parsed=valid)])
    observed = []
    monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", lambda *args, **kwargs:
                        observed.append(kwargs) or next(responses))
    nodes = SimpleNamespace(interviewer=SimpleNamespace(prepare_messages=lambda state, manifest: []), provider=object(),
                            config=SimpleNamespace(model_routing={"interviewer": SimpleNamespace(model="fake")}))
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "owner"})), nodes, Writer(), Evidence())
    workflow.durable = lambda name, state, operation: operation(state)
    pending = [{"call_id": "call_1", "content": "실행하지 않았습니다."}]
    state = {"mcp": {"snapshot": [], "round": 1, "results": [], "pending_tool_results": pending}}
    with pytest.raises(OutputLanguageError):
        workflow.mcp_decide(state)
    assert workflow.mcp_decide(state)["mcp"]["response"]["request_type"] == "feature"
    assert observed[0]["tool_result"] == pending
    # _complete_once는 성공한 출력 ID를 영속화하고 재시도에서 중복 전달을 제거한다.
    assert observed[1]["tool_result"] == pending


def test_native_tool_call_round_trip_uses_official_langchain_wire_contract():
    import json
    import httpx2
    from backend.mcp_client.workflow import native_tools
    from backend.providers.llm_provider import ChatModelProvider
    from tests.support.chat_model_fixture import transport
    from tests.support.model_helpers import response

    tool = {"name": "find", "description": "검색", "schema": {"type": "object", "properties": {
        "query": {"type": "string"}}, "required": ["query"]}, "schema_hash": "s1"}
    definitions = native_tools([({"id": "c1", "version": 1}, tool)])[0]
    name = definitions[0]["function"]["name"]
    answer = InterviewResponse(request_type="feature", assumptions=[], blocking_questions=[], additional_questions=[], pre_answers=[])
    first = response()
    first["output"] = [{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": name,
                        "arguments": '{"query":"안내"}', "status": "completed"}]
    second = response(content=[{"type": "output_text", "text": answer.model_dump_json(), "annotations": []}])
    payloads = iter([first, second])
    observed = []
    def handle(request):
        observed.append(json.loads(request.content))
        return httpx2.Response(200, json=next(payloads), request=request)
    with transport(handle):
        provider = ChatModelProvider(api_key="fake-test-value")
        call = provider.complete_result([{"role": "user", "content": "요청"}], model="gpt-6-luna", stage="interview",
                                        text_format=InterviewResponse, tools=definitions, conversation_id="conv_test")
        final = provider.complete_result([{"role": "tool", "tool_call_id": "call_1", "content": "결과"},
                                          {"role": "user", "content": "계속"}], model="gpt-6-luna", stage="interview",
                                         text_format=InterviewResponse, tools=definitions, conversation_id="conv_test")
    assert call.tool_calls == [{"id": "call_1", "name": name, "args": {"query": "안내"}}]
    assert final.parsed == answer
    assert observed[0]["tools"][0]["strict"] is False
    assert observed[0]["parallel_tool_calls"] is False
    assert observed[0]["text"]["format"]["strict"] is True
    assert observed[1]["input"][0]["type"] == "function_call_output"
    assert observed[1]["input"][0]["call_id"] == "call_1"
    assert all(item.get("type") != "function_call" for item in observed[1]["input"])
