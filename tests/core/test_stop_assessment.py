"""진전 없는 실행의 사용자 질문 전환과 중단 경계 회귀 검증."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.models import State
from backend.pipeline.agent_workflow import AgentWorkflow
from backend.pipeline.planner import allowed_tasks


def workflow():
    nodes = SimpleNamespace(
        interview=Mock(return_value={"blocking_questions": []}),
        review_resolution=Mock(return_value={"blocking_questions": []}),
        await_user=lambda state: {"status": "NEEDS_USER_INPUT", "blocking_questions": state["blocking_questions"]},
        critical_report=Mock(return_value={"critical_report": "report"}),
    )
    flow = AgentWorkflow(SimpleNamespace(config=SimpleNamespace(max_critic_passes=3)), nodes, None, None)
    flow.persist = Mock()
    flow._candidate_hash = lambda: "draft"
    flow.durable = lambda name, state, operation: operation(state)
    return flow


def test_completed_interview_requires_new_user_input():
    config = SimpleNamespace(max_critic_passes=3)
    state = State(run_id="test", status="ANALYZING", user_request="게임", completed_tasks=["interview"]).to_dict()
    flow = workflow()
    assert "interview" not in allowed_tasks(state, config)
    fresh = {**state, **flow.prepare({**state, "pending_input": {"action": "message"}})}
    assert "interview" in allowed_tasks(fresh, config)


@pytest.mark.parametrize("reason", ["execution_limit", "no_progress", "invalid_plan", "repair_limit"])
def test_explicit_stop_does_not_hide_another_model_classification(reason):
    flow = workflow()
    result = flow.blocked({"revision": 0}, stop_reason=reason)
    assert result["status"] == "CRITICAL_BLOCKED"
    flow.nodes.interview.assert_not_called()
    flow.nodes.review_resolution.assert_not_called()


def test_pending_question_skips_final_call():
    flow = workflow()
    assert flow.blocked({"blocking_questions": ["[Q] 질문"]})["status"] == "NEEDS_USER_INPUT"
    flow.nodes.interview.assert_not_called()


def test_final_review_reclassifies_exhausted_defect_and_preserves_result():
    flow = workflow()
    flow.nodes.review_resolution.return_value = {
        "blocking_questions": ["[Q] 키 변경을 지원할까요?"],
        "structured_issues": [{"resolution_kind": "user_decision"}],
    }
    state = {"requirement_lock_sheet": {"validated": True}, "structured_issues": [{"resolution_kind": "auto_fix", "severity": "major"}],
             "final_resolution_keys": ["legacy-assessment"]}
    result = flow.ask({**state, "plan": {"action": "ask_user", "reason": "키 정책을 확인해야 합니다."}})
    assert flow.nodes.review_resolution.call_args.kwargs == {"final": True}
    assert result["structured_issues"][0]["resolution_kind"] == "user_decision"
    assert result["status"] == "NEEDS_USER_INPUT"


def test_system_limit_keeps_cause_and_does_not_call_assessment():
    flow = workflow()
    result = flow.blocked({"revision": 0}, "동일한 작업이 반복되었습니다.", "no_progress")
    assert result["status"] == "CRITICAL_BLOCKED"
    assert result["stop_reason"] == "no_progress"
    assert "동일한 작업" in result["wait_reason"]
    assert "같은 문제가 남을 수" in result["wait_reason"]
    again = flow.blocked(result, stop_reason="no_progress")
    assert again["status"] == "CRITICAL_BLOCKED"
    flow.nodes.interview.assert_not_called()


def test_model_plan_wording_cannot_bypass_repeat_detection():
    flow = workflow()
    state = {"plan": {"action": "knowledge_search", "reason": "확인", "target": "first", "input_refs": []},
             "execution_segment": 1, "revision": 0}
    captured = []
    flow.durable = lambda name, current, operation: {}
    flow.persist = lambda name, current: captured.append(current)
    first = flow.execute(state)
    signature = first["task_results"][-1]["signature"]
    state.update(task_results=[{"action": "knowledge_search", "signature": signature, "segment": 1}] * 2,
                 plan={"action": "knowledge_search", "reason": "다른 표현", "target": "second", "input_refs": ["new"]})
    flow.blocked = Mock(return_value={"status": "CRITICAL_BLOCKED"})
    result = flow.execute(state)
    flow.blocked.assert_not_called()
    assert "knowledge_search" in result["execution_constraints"]["repeated_actions"]
    assert "knowledge_search" not in allowed_tasks({**state, **result}, flow.engine.config)
    assert "ask_user" in allowed_tasks({**state, **result}, flow.engine.config)


@pytest.mark.parametrize("answered", [False, True])
@pytest.mark.parametrize("passes", [1, 3])
def test_exhausted_review_is_reclassified_but_confirmed_answer_is_not_asked(monkeypatch, answered, passes):
    import backend.pipeline.tasks as tasks
    from backend.models import IssuePacket, ReviewResolutionResponse
    from backend.services.review_resolution import defect_identity, decision_identity
    from fakes import resolution_value

    issue = IssuePacket("I1", "controls", "major", True, "controls", "키 변경 여부가 미정입니다.",
                        "키 변경 정책을 반영하세요.", decision_key="key_binding")
    auto_issue = IssuePacket("I2", "tests", "major", True, "controls_tests", "검증 시나리오가 누락됐습니다.",
                             "확정 동작의 검증 시나리오를 보완하세요.", decision_key="controls_tests")
    sheet = Mock()
    sheet.require_validated.return_value = sheet
    sheet.to_dict.return_value = {}
    monkeypatch.setattr(tasks.RequirementLockSheet, "from_dict", lambda _: sheet)
    monkeypatch.setattr(tasks, "validate_locked_sources", lambda value, _: value)
    packet = ReviewResolutionResponse.model_validate(resolution_value([{
        **issue.to_dict(), "resolution_kind": "user_decision", "decision_question": "키 변경을 지원할까요?",
    }, auto_issue.to_dict()]))
    complete = Mock(return_value=packet)
    monkeypatch.setattr(tasks, "complete_with_usage", complete)
    node = object.__new__(tasks.WorkflowTasks)
    node.writer = Mock()
    node.writer.read_text.return_value = "Draft"
    node.config = SimpleNamespace(max_critic_passes=3, model_routing={"critic": SimpleNamespace(model="fake")})
    node.provider = None
    state = {
        "user_request": "키보드 게임", "requirement_lock_sheet": {}, "critic_pass_count": passes,
        "structured_issues": [issue.to_dict(), auto_issue.to_dict()], "diagnosed_keys": [defect_identity(issue)],
        "resolution_history": [{"issues": [issue.to_dict()]}],
    }
    if answered:
        state["requirement_lock_sheet"] = {"user_answers": [{"question_id": "Q1", "question": "키 변경을 지원할까요?", "answer": "지원합니다"}]}
        state["review_questions"] = [{"decision_key": decision_identity(issue), "question_id": "Q1"}]
    result = node.review_resolution(state, final=True)
    assert complete.call_count == 1
    assert result["resolution_stop"] is (passes > 1)
    assert bool(result["blocking_questions"]) is not answered
    assert result["structured_issues"][0]["resolution_kind"] == ("auto_fix" if answered else "user_decision")
    assert result["structured_issues"][1]["resolution_kind"] == "auto_fix"
    assert result["structured_issues"][1]["decision_question"] is None
    if answered:
        assert result["structured_issues"][0]["decision_answer_id"] == "Q1"
