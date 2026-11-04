"""확정된 검토 전이와 모델의 부당한 중단에 대한 회귀 검증."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.models import State
from backend.pipeline.execution_policy import evaluate_execution, execution_constraints, task_signature
from backend.pipeline.planner import plan_next
from tests.support.planner_helpers import decision
from tests.support.assessment_helpers import workflow


def reviewed():
    return State(run_id="ready", status="CRITIQUING", user_request="명세",
                 critic_pass_count=3, resolution_stop=True, refinement={"termination": "max_score"},
                 completed_tasks=["spec_compile", "checklist_critic", "review_resolution"]).to_dict()


@pytest.mark.parametrize("action", ["review_resolution", "compose_candidate"])
def test_required_transition_overrides_repeat_filter(action):
    state = reviewed()
    if action == "review_resolution":
        state["completed_tasks"].remove("review_resolution")
    signature = task_signature(state, action)
    state["task_results"] = [{"action": action, "signature": signature, "segment": 0,
                              "status": "completed"}] * 2
    result = evaluate_execution(state, SimpleNamespace(max_critic_passes=3))
    assert result.required_action == action
    assert result.eligibility[action].allowed
    assert not result.stop_reason


@pytest.mark.parametrize("needs_resolution", [False, True])
def test_reviewed_result_reaches_approval_wait_without_model(monkeypatch, needs_resolution):
    import backend.pipeline.agent_workflow as agent
    flow = workflow()
    flow.nodes.compose_candidate = Mock(return_value={"status": "PASS_PENDING_USER_APPROVAL"})
    flow.writer = Mock()
    flow.writer.read_text.return_value = "draft"
    planner = Mock(side_effect=AssertionError("확정된 전이에 모델 호출 금지"))
    monkeypatch.setattr(agent, "plan_next", planner)
    config = {"configurable": {"thread_id": "ready"}}
    # prepare는 새 실행 예산을 초기화하므로 저장 구간의 재개 상태로 직접 연결한다.
    flow.prepare = lambda state: {}
    graph = flow.build(InMemorySaver())
    state = reviewed()
    if needs_resolution:
        state["completed_tasks"].remove("review_resolution")
    signature = task_signature(state, "compose_candidate")
    state["task_results"] = [{"action": "compose_candidate", "signature": signature,
                              "segment": 0, "status": "completed"}] * 2
    graph.invoke(state, config)
    saved = graph.get_state(config)
    assert saved.values["allowed_actions"] == ["approve", "message", "revise", "retry"]
    assert saved.tasks[0].interrupts
    flow.nodes.compose_candidate.assert_called_once()
    assert flow.nodes.review_resolution.call_count == int(needs_resolution)
    planner.assert_not_called()


@pytest.mark.parametrize("recover", [True, False])
def test_unverified_model_block_is_replanned_with_bounded_attempts(monkeypatch, recover):
    import backend.pipeline.planner as planner
    complete = Mock(side_effect=[decision("blocked"), decision("knowledge_search" if recover else "blocked")])
    monkeypatch.setattr(planner, "_complete_once", complete)
    context = SimpleNamespace(writer=None, provider=None,
        config=SimpleNamespace(max_critic_passes=3, model_routing={"planner": SimpleNamespace(model="fake")}))
    result = plan_next({}, context)
    assert complete.call_count == 2
    if recover:
        assert result["action"] == "knowledge_search"
    else:
        assert result["stop_reason"] == "invalid_plan"


def test_repeat_counter_excludes_other_actions_segments_signatures_and_failed_results():
    state = {"execution_segment": 2}
    signature = task_signature(state, "knowledge_search")
    base = {"action": "knowledge_search", "signature": signature, "segment": 2, "status": "completed"}
    state["task_results"] = [base, {**base, "action": "interview"}, {**base, "segment": 1},
                             {**base, "signature": "old"}, {**base, "status": "failed"}]
    config = SimpleNamespace(max_critic_passes=3)
    assert not execution_constraints(state, config)["repeated_actions"]
    state["task_results"].append(base)
    assert execution_constraints(state, config)["repeated_actions"] == ["knowledge_search"]


def test_execution_diagnostic_is_allowlisted_and_old_states_remain_readable():
    from backend.access.service import user_payload
    state = State.from_dict(reviewed())
    assert state.execution_diagnostic == {}
    diagnostic = {"stop_code": "repair_limit", "target_action": "spec_compile",
                  "block_reasons": ["review_budget_exhausted"], "review_pass_count": 3, "review_pass_limit": 3}
    result = user_payload({"state": {"stop_reason": "repair_limit", "execution_diagnostic": {
        **diagnostic, "untrusted_model_output": "must not escape"}}})
    assert result["state"]["execution_diagnostic"] == diagnostic
    assert result["state"]["stop_reason"] == "repair_limit"


@pytest.mark.parametrize("pending", [False, True])
def test_required_candidate_never_bypasses_unresolved_product_decisions(pending):
    from backend.models import IssuePacket
    state = reviewed()
    issue = IssuePacket("I1", "controls", "minor", False, "controls", "결정 미확정", "확정 필요",
                        decision_key="controls", resolution_kind="user_decision")
    state["structured_issues"] = [issue.to_dict()]
    if pending:
        state["blocking_questions"] = ["[Q1] 정책을 선택해주세요."]
    result = evaluate_execution(state, SimpleNamespace(max_critic_passes=3))
    assert not result.eligibility["compose_candidate"].allowed
    assert result.required_action == "ask_user"


@pytest.mark.parametrize("diagnostic", [{}, {"stop_code": "invalid_plan", "target_action": "",
    "block_reasons": [], "review_pass_count": 0, "review_pass_limit": 3}])
def test_job_query_only_publishes_present_diagnostic(monkeypatch, diagnostic):
    from backend.application.job_queries import JobQueries
    import backend.application.job_queries as queries
    history = SimpleNamespace(graph=lambda: {}, conversation=lambda: [])
    monkeypatch.setattr(queries, "ExecutionHistory", lambda _: history)
    access = SimpleNamespace(documents=lambda _: None, get=lambda _: {"status": "CRITICAL_BLOCKED"},
        read_json=lambda *_: None, read_text=lambda *_: None,
        state=lambda _: {"execution_diagnostic": diagnostic})
    query = JobQueries(access)
    query.summary = lambda _: {"id": "test", "status": "CRITICAL_BLOCKED"}
    result = query.public("test")
    assert ("execution_diagnostic" in result["state"]) == bool(diagnostic)



@pytest.mark.parametrize("reason", ["model_blocked", "legacy_unknown_reason"])
def test_unknown_stop_preserves_code_without_inventing_system_cause(reason):
    flow = workflow()
    result = flow.blocked({"plan": {"reason": "후보 작성이 시스템 제약으로 금지되었습니다."}}, stop_reason=reason)
    assert result["stop_reason"] == reason
    assert "상세 중단 진단이 없습니다" in result["wait_reason"]
    assert "후보 작성이 시스템 제약" not in result["wait_reason"]
    assert result["execution_diagnostic"]["block_reasons"] == []
