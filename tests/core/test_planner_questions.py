"""모델 계획에 따른 질문 생성과 실행 제약의 회귀 검증."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.errors import ReviewValidationError
from backend.models import State
from backend.pipeline.agent_workflow import AgentWorkflow
from backend.pipeline.planner import (
    DECISION_STEP_RESERVE, EXECUTION_STEP_LIMIT, PlannerDecision,
    allowed_tasks, plan_next, task_signature,
)
from test_stop_assessment import workflow


def decision(action):
    return PlannerDecision(goal="게임 명세 확정", tasks=[], action=action, target="조작 키 배치",
                           input_refs=[], expected_result="사용자 결정 확인", reason="키 배치 결정이 필요합니다.",
                           affected_requirement_ids=[])


def test_planner_receives_repair_evidence_and_can_request_new_questions(monkeypatch):
    import backend.pipeline.planner as planner

    state = State(run_id="test", status="CRITIQUING", user_request="게임", critic_pass_count=3,
                  resolution_history=[{"issues": [], "action": "repair"}],
                  review_questions=[{"question_id": "Q1", "question": "플랫폼", "answer": "Windows"}],
                  diagnosed_keys=["controls:key_binding"]).to_dict()
    context = SimpleNamespace(config=SimpleNamespace(max_critic_passes=3, model_routing={"planner": SimpleNamespace(model="fake")}),
                              writer=None, provider=None)
    complete = Mock(return_value=decision("ask_user"))
    monkeypatch.setattr(planner, "_complete_once", complete)
    assert plan_next(state, context)["action"] == "ask_user"
    payload = json.loads(complete.call_args.args[2][1]["content"])
    for key in ("resolution_history", "review_questions", "diagnosed_keys", "critic_pass_count"):
        assert payload[key] == state[key]
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
    state = {"execution_segment": 1, "segment_steps": EXECUTION_STEP_LIMIT,
             "plan": {"action": "ask_user"}}
    signature = task_signature(state, "ask_user")
    state["task_results"] = [{"action": "ask_user", "signature": signature, "segment": 1}] * 2
    assert allowed_tasks(state, flow.engine.config) == ["blocked"]
    assert flow.ask(state)["allowed_actions"] == []
    flow.nodes.interview.assert_not_called()


def test_execution_limit_reserves_model_decisions_before_hard_stop(monkeypatch):
    import backend.pipeline.agent_workflow as agent_workflow

    flow = workflow()
    monkeypatch.setattr(agent_workflow, "plan_next", lambda state, nodes: decision("ask_user").model_dump())
    for step in range(EXECUTION_STEP_LIMIT, EXECUTION_STEP_LIMIT + DECISION_STEP_RESERVE):
        state = {"segment_steps": step}
        result = flow.planner(state)
        assert result["plan"]["action"] == "ask_user"
        assert result["execution_constraints"]["decision_only"]
        assert allowed_tasks({**state, **result}, flow.engine.config) == ["ask_user", "blocked"]
    result = flow.planner({"segment_steps": EXECUTION_STEP_LIMIT + DECISION_STEP_RESERVE})
    assert result["plan"]["action"] == "blocked"
    assert result["plan"]["stop_reason"] == "execution_limit"
    assert flow.blocked(result)["status"] == "CRITICAL_BLOCKED"


def test_interview_receives_planner_intent_through_real_prompt_preparation():
    from backend.infrastructure.prompt_context import prepare_context
    from backend.services.interviewer import _build_messages

    state = {"plan": {"action": "ask_user", "target": "키 배치", "reason": "사용자 결정 필요"},
             "execution_constraints": {"decision_only": True}, "task_results": [{"action": "interview", "status": "no_questions"}]}
    prepared, _ = prepare_context(None, _build_messages("게임", {"files": []}, [], [], state), "interview")
    canonical = json.loads(next(item["content"].split("\n", 1)[1] for item in prepared
                                if item["content"].startswith("Canonical context:\n")))
    assert canonical["planner_intent"]["target"] == "키 배치"
    assert canonical["execution_constraints"] == {"decision_only": True}
    assert canonical["previous_task_outcomes"] == state["task_results"]


def test_graph_generates_question_interrupts_and_replans_with_answer(monkeypatch):
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
                  requirement_lock_sheet={"validated": True}, structured_issues=[{"status": "open", "severity": "major"}]).to_dict()
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
