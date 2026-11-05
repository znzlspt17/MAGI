"""모델 계획에 따른 질문 생성과 실행 제약의 회귀 검증."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.errors import ReviewValidationError
from backend.models import State
from backend.pipeline.agent_workflow import AgentWorkflow
from backend.pipeline.planner import (
    PlannerDecision,
    allowed_tasks, plan_next, task_signature,
)
from tests.support.assessment_helpers import workflow
from tests.support.planner_helpers import decision


def test_planner_receives_repair_evidence_and_can_request_new_questions(monkeypatch):
    import backend.pipeline.planner as planner

    state = State(run_id="test", status="CRITIQUING", user_request="게임", critic_pass_count=3,
                  resolution_history=[{"issues": [], "action": "repair"}],
                  review_questions=[{"question_id": "Q1", "question": "플랫폼", "answer": "Windows"}],
                  diagnosed_keys=["controls:key_binding"]).to_dict()
    context = SimpleNamespace(config=SimpleNamespace(max_critic_passes=3, model_routing={"planner": SimpleNamespace(model="fake")}),
                              writer=None, provider=None)
    state.update(remaining_steps=50, execution_constraints={"decision_only": True})
    complete = Mock(return_value=decision("ask_user"))
    monkeypatch.setattr(planner, "_complete_once", complete)
    assert plan_next(state, context)["action"] == "ask_user"
    payload = json.loads(complete.call_args.args[2][1]["content"])
    for key in ("resolution_history", "review_questions", "diagnosed_keys", "critic_pass_count"):
        assert payload[key] == state[key]
    assert "remaining_steps" not in payload
    assert "decision_only" not in payload["execution_constraints"]
    assert payload["execution_constraints"]["remaining_review_passes"] == 0
    assert "ask_user" in payload["allowed_actions"]
    assert "spec_compile" not in payload["allowed_actions"]


def test_review_limit_returns_to_planner_without_forcing_block():
    flow = workflow()
    flow.nodes.review_resolution.return_value = {"resolution_stop": True, "blocking_questions": []}
    flow.blocked = Mock()
    state = {"plan": {"action": "review_resolution", "reason": "판단"},
             "completed_tasks": ["checklist_critic"], "critic_pass_count": 3}
    result = flow.execute(state)
    assert result["resolution_stop"]
    flow.blocked.assert_not_called()
    assert "ask_user" in allowed_tasks({**state, **result}, flow.engine.config)


def test_empty_question_assessment_replans_and_does_not_wait():
    flow = workflow()
    state = {"plan": {"action": "ask_user", "reason": "사용자 확인"}}
    result = flow.ask(state)
    assert result["allowed_actions"] == []
    assert result["task_results"][-1]["status"] == "no_questions"
    assert result.get("status") != "NEEDS_USER_INPUT"


@pytest.mark.parametrize("succeeds", [True, False])
def test_question_generation_uses_bounded_validation_repairs(succeeds):
    flow = workflow()
    error = ReviewValidationError(stage="review_resolution", check="source_reference")
    question = {"blocking_questions": ["[Q] 키 배치는 어떻게 할까요?"]}
    flow.nodes.review_resolution.side_effect = [error, question] if succeeds else [error] * 4
    state = {"plan": {"action": "ask_user"}, "requirement_lock_sheet": {"validated": True},
             "structured_issues": [{"status": "open", "severity": "major"}]}
    if succeeds:
        assert flow.ask(state)["status"] == "NEEDS_USER_INPUT"
        assert flow.nodes.review_resolution.call_count == 2
    else:
        with pytest.raises(ReviewValidationError):
            flow.ask(state)
        assert flow.nodes.review_resolution.call_count == 4


def test_repeated_empty_question_generation_is_not_available_again():
    flow = workflow()
    state = {"execution_segment": 1,
             "plan": {"action": "ask_user"}}
    signature = task_signature(state, "ask_user")
    state["task_results"] = [{"action": "ask_user", "signature": signature, "segment": 1, "status": "completed"}] * 2
    assert "ask_user" not in allowed_tasks(state, flow.engine.config)
    assert flow.ask(state)["allowed_actions"] == []
    flow.nodes.interview.assert_not_called()


@pytest.mark.parametrize("remaining", [1, 2, 3])
def test_native_limit_skips_planner_and_assessment(monkeypatch, remaining):
    import backend.pipeline.agent_workflow as agent_workflow

    flow = workflow()
    plan = Mock()
    monkeypatch.setattr(agent_workflow, "plan_next", plan)
    state = {"remaining_steps": remaining, "blocking_questions": ["question"],
             "requirement_lock_sheet": {"validated": True}, "structured_issues": [{"severity": "major"}]}
    result = flow.planner(state)
    stopped = flow.blocked({**state, **result})
    assert stopped["stop_reason"] == "execution_limit"
    assert stopped["wait_reason"] == "실행 안전 한도에 도달해 중단했습니다. 저장된 결과에서 추가 실행할 수 있습니다."
    plan.assert_not_called()
    flow.nodes.interview.assert_not_called()
    flow.nodes.review_resolution.assert_not_called()
    flow.nodes.critical_report.assert_not_called()


def test_legacy_constraints_do_not_block_candidate(monkeypatch):
    import backend.pipeline.agent_workflow as agent_workflow

    flow = workflow()
    state = {"run_id": "test", "status": "CRITIQUING", "user_request": "게임",
             "segment_steps": 100, "execution_constraints": {"decision_only": True},
             "completed_tasks": ["checklist_critic", "review_resolution"], "structured_issues": []}
    restored = State.from_dict(state).to_workflow_state()
    assert "segment_steps" not in restored
    assert "remaining_steps" not in restored
    restored["refinement"] = {"termination": "max_score"}
    assert "compose_candidate" in allowed_tasks(restored, flow.engine.config)
    monkeypatch.setattr(agent_workflow, "plan_next", lambda state, nodes: decision("compose_candidate").model_dump())
    result = flow.planner(restored)
    assert result["plan"]["action"] == "compose_candidate"
    assert "decision_only" not in result["execution_constraints"]


@pytest.mark.parametrize("limit", [8, 9, 128])
def test_graph_native_limit_interrupts_and_resumes(monkeypatch, limit):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    import backend.pipeline.agent_workflow as agent_workflow

    flow = workflow()
    calls = []
    def plan(state, nodes):
        calls.append(state["remaining_steps"])
        return decision("knowledge_search").model_dump()
    monkeypatch.setattr(agent_workflow, "plan_next", plan)
    flow.execute = lambda state: {}
    graph = flow.build(InMemorySaver())
    config = {"configurable": {"thread_id": "limit"}, "recursion_limit": limit}
    state = State(run_id="test", status="ANALYZING", user_request="게임").to_dict()
    graph.invoke(state, config)
    snapshot = graph.get_state(config)
    assert snapshot.tasks[0].interrupts
    assert snapshot.values["stop_reason"] == "execution_limit"
    assert "remaining_steps" not in snapshot.values
    assert min(calls) > 3
    count = len(calls)
    graph.invoke(Command(resume={"action": "retry", "state": snapshot.values}), config)
    assert len(calls) > count
    assert graph.get_state(config).tasks[0].interrupts


def test_graph_finishes_candidate_after_more_than_22_tasks(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    import backend.pipeline.agent_workflow as agent_workflow

    flow = workflow()
    calls = []
    def plan(state, nodes):
        calls.append(state["remaining_steps"])
        return decision("compose_candidate" if len(calls) > 22 else "knowledge_search").model_dump()
    monkeypatch.setattr(agent_workflow, "plan_next", plan)
    def execute(state):
        if state["plan"]["action"] == "compose_candidate":
            return {"allowed_actions": ["approve", "message", "revise"], "candidate_hash": "draft"}
        return {}
    flow.execute = execute
    graph = flow.build(InMemorySaver())
    config = {"configurable": {"thread_id": "candidate"}, "recursion_limit": 128}
    graph.invoke(State(run_id="test", status="CRITIQUING", user_request="게임").to_dict(), config)
    snapshot = graph.get_state(config)
    assert len(calls) == 23
    assert snapshot.values["allowed_actions"] == ["approve", "message", "revise"]
    assert snapshot.tasks[0].interrupts


def test_legacy_checkpoint_resumes_without_removed_counter(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from backend.models import WorkflowState
    import backend.pipeline.agent_workflow as agent_workflow

    class LegacyWorkflowState(WorkflowState):
        segment_steps: int

    flow = workflow()
    monkeypatch.setattr(agent_workflow, "plan_next", lambda state, nodes: decision("blocked").model_dump())
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "legacy"}, "recursion_limit": 128}
    with monkeypatch.context() as patch:
        patch.setattr(agent_workflow, "WorkflowState", LegacyWorkflowState)
        old_graph = flow.build(saver)
    old_graph.invoke({**State(run_id="test", status="ANALYZING", user_request="게임").to_dict(),
                      "segment_steps": 100, "execution_constraints": {"decision_only": True}}, config)
    old = old_graph.get_state(config)
    assert old.values["segment_steps"] == 100
    assert old.tasks[0].interrupts
    graph = flow.build(saver)
    incoming = State.from_dict(old.values).to_workflow_state()
    graph.invoke(Command(resume={"action": "retry", "state": incoming}), config)
    resumed = graph.get_state(config)
    assert resumed.tasks[0].interrupts
    assert "segment_steps" not in resumed.values
    assert "remaining_steps" not in resumed.values
    assert "decision_only" not in resumed.values["execution_constraints"]


def test_interview_receives_planner_intent_through_real_prompt_preparation():
    from backend.infrastructure.prompt_context import prepare_context
    from backend.services.interviewer import _build_messages

    state = {"plan": {"action": "ask_user", "target": "키 배치", "reason": "사용자 결정 필요"},
             "execution_constraints": {"remaining_review_passes": 1}, "task_results": [{"action": "interview", "status": "no_questions"}]}
    prepared, _ = prepare_context(None, _build_messages("게임", {"files": []}, [], [], state), "interview")
    canonical = json.loads(next(item["content"].split("\n", 1)[1] for item in prepared
                                if item["content"].startswith("확정 문맥:\n")))
    assert canonical["planner_intent"]["target"] == "키 배치"
    assert canonical["execution_constraints"] == {"remaining_review_passes": 1}
    assert canonical["previous_task_outcomes"] == state["task_results"]


def test_graph_generates_question_interrupts_and_replans_with_answer(monkeypatch):
    from backend.models import RequirementLockSheet, RequirementItem
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    import backend.pipeline.planner as planner

    flow = workflow()
    flow.nodes.config = SimpleNamespace(max_critic_passes=3, model_routing={"planner": SimpleNamespace(model="fake")})
    flow.nodes.writer = None
    flow.nodes.provider = None
    payloads = []

    def plan(writer, provider, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        payloads.append(payload)
        return decision("blocked" if payload.get("confirmed_user_sources") else "ask_user")

    monkeypatch.setattr(planner, "_complete_once", plan)
    flow.nodes.review_resolution.return_value = {
        "blocking_questions": ["[Q] 조작 키 배치를 정해주세요."],
        "question_forms": {"Q": {"input_type": "text", "options": []}},
        "awaiting_input_reason": "review",
    }
    graph = flow.build(InMemorySaver())
    config = {"configurable": {"thread_id": "questions"}}
    state = State(run_id="test", status="CRITIQUING", user_request="게임", critic_pass_count=3,
                  requirement_lock_sheet=RequirementLockSheet("lock", "feature", "게임", [],
                      mandatory_requirements=[RequirementItem("REQ-001", "Support player controls.")]).to_dict(),
                  structured_issues=[{"status": "open", "severity": "major"}]).to_dict()
    graph.invoke(state, config)
    snapshot = graph.get_state(config)
    assert snapshot.tasks[0].interrupts
    assert snapshot.values["status"] == "NEEDS_USER_INPUT"
    assert snapshot.values["question_forms"]["Q"]["input_type"] == "text"
    answered = {**snapshot.values, "blocking_questions": [], "confirmed_user_sources": {"user_answer:Q": "방향키"}}
    graph.invoke(Command(resume={"action": "answer", "state": answered}), config)
    assert payloads[-1]["confirmed_user_sources"] == {"user_answer:Q": "방향키"}
    assert graph.get_state(config).values["revision"] == 1
    assert flow.nodes.review_resolution.call_count == 1
    assert flow.nodes.review_resolution.call_args.kwargs == {"final": True}
