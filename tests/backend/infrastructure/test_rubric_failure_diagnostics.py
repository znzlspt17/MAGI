"""루브릭 실패의 안전한 보정 안내와 로그를 검증한다."""

import io
import json
from contextlib import nullcontext
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.errors import ReviewValidationError
from backend.infrastructure.stage_retry import retry_messages
from backend.pipeline.builder import _stage
from protocol.logging import configure_logging
from tests.support.rubric_helpers import case


@pytest.mark.parametrize(("reason", "expected"), [
    ("requirement_unknown", "requirement_id"),
    ("basis_reference_invalid", "reference"),
    ("basis_quote_not_found", "부분 문자열"),
    ("importance_invalid", "secondary"),
])
def test_basis_retry_guidance_is_specific(reason, expected):
    error = ReviewValidationError(["PRIVATE_RESPONSE"], stage="rubric_generate", check="rubric_basis", reason=reason,
                                  context={"requirement_id": "REQ-001"})
    result = retry_messages([], stage="rubric_generate", attempt=1, error=error)
    payload = json.loads(result[-1]["content"].split("\n", 1)[1])
    assert expected in " ".join(payload["validation_failures"])
    assert payload["validation_reason"] == reason
    assert "PRIVATE_RESPONSE" not in str(payload)


def test_basis_failure_logs_reason_reference_and_actual_attempt_without_response(monkeypatch):
    from backend.server.job_manager import JobManager
    from gateway.logs import normalize

    stream = io.StringIO()
    configure_logging("backend", stream=stream)
    error = ReviewValidationError(["PRIVATE_RESPONSE"], stage="rubric_generate", check="rubric_basis",
                                  reason="basis_quote_not_found", context={"requirement_id": "REQ-001"})
    engine = Mock()
    engine.execute.side_effect = lambda *a, **kw: _stage("spec_compile", lambda state: (_ for _ in ()).throw(error), None)({})
    history = Mock()
    monkeypatch.setattr("backend.server.job_manager.ExecutionHistory", Mock(return_value=history))
    job = {"execution_id": "a" * 32, "request": "PRIVATE_REQUEST"}
    manager = SimpleNamespace(lock=RLock(), _get_locked=lambda ident: job,
        knowledge=SimpleNamespace(store=SimpleNamespace(transaction=nullcontext)),
        _save_locked=Mock(return_value=True), _notify=Mock(), _set_error_metadata=Mock(),
        workspace=SimpleNamespace(documents=Mock(), engine=Mock(return_value=engine), state=lambda ident: {}))
    try:
        JobManager._run_logged(manager, "b" * 32, "retry", {})
    finally:
        configure_logging("backend")
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(rows) == 5
    assert all(row["validation_reason"] == "basis_quote_not_found" for row in rows)
    assert all(row["validation_requirement_id"] == "REQ-001" for row in rows)
    assert [row["attempt"] for row in rows] == [1, 2, 3, 4, 4]
    assert all(row["max_attempts"] == 4 for row in rows)
    assert normalize(rows[-1])["fields"]["validation_requirement_id"] == "REQ-001"
    assert "PRIVATE_RESPONSE" not in stream.getvalue()
    assert "PRIVATE_REQUEST" not in stream.getvalue()


def test_invalid_rubric_is_corrected_after_specific_retry_feedback(case):
    from backend.infrastructure.stage_retry import current_messages
    from backend.services import rubric

    case.docs.data.clear()
    seen = []
    def respond(writer, provider, messages, *, model, stage, temperature):
        sent = current_messages(messages, stage)
        seen.append(sent)
        value = case.response.model_copy(deep=True)
        if len(seen) == 1:
            value.items[0].basis[0].quote = "PRIVATE_FABRICATED_QUOTE"
        else:
            feedback = json.loads(sent[-1]["content"].split("\n", 1)[1])
            assert feedback["validation_reason"] == "basis_quote_not_found"
            assert "부분 문자열" in feedback["validation_failures"][0]
            assert "PRIVATE_FABRICATED_QUOTE" not in str(feedback)
        return value

    case.complete.side_effect = respond
    events = []
    generate = _stage("spec_compile", lambda state: rubric.ensure_rubric(case.docs, None, "model", case.sheet, state), events.append)
    result = generate({**case.state, "rubric": {}})
    assert result["items"][0]["basis"][0]["quote"] == case.sheet.mandatory_requirements[0].text
    assert len(seen) == 2
    assert [event["state"] for event in events] == ["started", "retrying", "completed"]


def test_stage_and_terminal_history_expose_same_safe_attempts():
    from backend.server.diagnostics import diagnose_exception
    from tests.backend.application.test_execution_history_inputs import history_for

    data = {"nodes": [], "executions": [{"id": "run", "action": "answer"}]}
    history = history_for(data)
    history.documents = SimpleNamespace(usage=lambda: {"attempts": []})
    error = ReviewValidationError(["PRIVATE_RESPONSE"], stage="rubric_generate", check="rubric_basis",
                                  reason="basis_quote_not_found", context={"requirement_id": "REQ-001"})
    def progress(event):
        history.stage("run", event["stage"], event["state"], result=event.get("result"))
    with pytest.raises(ReviewValidationError):
        _stage("spec_compile", lambda _: (_ for _ in ()).throw(error), progress)({})
    history.terminal("run", "error", "생성 실패", result={"diagnostic": diagnose_exception(error)})
    failed = next(item for item in data["nodes"] if item["stage"] == "spec_compile")
    terminal = next(item for item in data["nodes"] if item["stage"] == "workflow")
    stage_diag = history.detail(failed["id"])["result"]["diagnostic"]
    terminal_diag = history.detail(terminal["id"])["result"]["diagnostic"]
    for diagnostic in (stage_diag, terminal_diag):
        assert diagnostic["error_stage"] == "rubric_generate"
        assert diagnostic["validation_reason"] == "basis_quote_not_found"
        assert diagnostic["context"] == {"requirement_id": "REQ-001"}
        assert [item["attempt"] for item in diagnostic["attempts"]] == [1, 2, 3, 4]
        assert all(item["validation_reason"] == "basis_quote_not_found" for item in diagnostic["attempts"])
    assert "PRIVATE_RESPONSE" not in str(data)


def test_failed_rubric_resume_uses_checkpoint_and_preserves_answers():
    from langgraph.checkpoint.memory import InMemorySaver
    from backend.models import State
    from tests.support.assessment_helpers import workflow

    flow = workflow()
    flow.nodes.requirement_lock = Mock()
    flow.planner = lambda state: {"plan": {"action": "spec_compile", "reason": "확정 요구사항으로 생성"}}
    calls = []
    def compile_stage(state):
        calls.append(state)
        if len(calls) <= 4:
            raise ReviewValidationError(stage="rubric_generate", check="rubric_basis", reason="basis_quote_not_found")
        return {"allowed_actions": ["approve"]}
    flow.execute = _stage("spec_compile", compile_stage, None)
    graph = flow.build(InMemorySaver())
    config = {"configurable": {"thread_id": "rubric-retry"}}
    original = State(run_id="retry", status="COMPILING", user_request="게임",
                     confirmed_user_sources={"user_answer:Q1": "Windows"},
                     completed_tasks=["interview", "requirement_lock_stage"]).to_dict()
    with pytest.raises(ReviewValidationError):
        graph.invoke(original, config)
    snapshot = graph.get_state(config)
    assert snapshot.next == ("execute",)
    graph.invoke(None, config)
    final = graph.get_state(config).values
    assert len(calls) == 5
    assert final["confirmed_user_sources"] == original["confirmed_user_sources"]
    assert final["completed_tasks"] == original["completed_tasks"]
    flow.nodes.interview.assert_not_called()
    flow.nodes.requirement_lock.assert_not_called()
