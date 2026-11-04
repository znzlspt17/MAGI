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
    snapshot = [{"connection_id": "c1", "connection_version": 1, "name": "search", "schema_hash": "v1"}]
    tool = {"name": "search", "description": "문서 검색", "schema": {"type": "object"}, "schema_hash": "v1"}
    monkeypatch.setattr(MCPService, "available", lambda self, owner, items: [({"id": "c1", "version": 1}, tool)])
    calls = []
    monkeypatch.setattr(MCPService, "invoke", lambda self, owner, items, cid, name, arguments:
                        calls.append((cid, name, arguments)) or {"status": "ok", "text": "공식 문서"})
    monkeypatch.setattr("backend.infrastructure.prompt_context.prepare_context", lambda writer, messages, stage:
                        (messages, SimpleNamespace(restore=lambda result: result)))
    answer = InterviewResponse(request_type="feature", assumptions=[], blocking_questions=[], additional_questions=[], pre_answers=[])
    responses = iter([
        MCPDecision(action="tool", connection_id="c1", tool_name="search", arguments_json='{"query":"hello"}', interview=None),
        MCPDecision(action="finish", connection_id=None, tool_name=None, arguments_json=None, interview=answer),
    ])
    monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", lambda *args, **kwargs: next(responses))
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
    from chat_model_fixture import transport
    from backend.providers.llm_provider import ChatModelProvider
    from test_models import response

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
    decision = MCPDecision(action="finish", connection_id=None, tool_name=None, arguments_json=None, interview=answer)
    monkeypatch.setattr("backend.infrastructure.provider_call._complete_once", lambda *args, **kwargs: decision)
    nodes = SimpleNamespace(interviewer=SimpleNamespace(prepare_messages=lambda state, manifest: []), provider=object(),
                            config=SimpleNamespace(model_routing={"interviewer": SimpleNamespace(model="fake")}))
    workflow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(job={"owner_id": "owner"})), nodes, Writer(), Evidence())
    workflow.durable = lambda name, state, operation: operation(state)
    with pytest.raises(OutputLanguageError):
        workflow.mcp_decide({"mcp": {"snapshot": [{"connection_id": "c1"}], "round": 0, "results": []}})
    restore.assert_called_once_with(answer)
