"""사용자 입력마다 보완 예산을 갱신하고 한도에서는 명시적 재개를 기다린다."""

from unittest.mock import Mock

import pytest

from backend.models import IssuePacket, State
from backend.pipeline.planner import allowed_tasks, execution_constraints, plan_next
from test_stop_assessment import workflow


def exhausted():
    issue = IssuePacket("I1", "weapons", "major", True, "boss_weapon",
                        "보스 격파 후 무기 처리가 초안에 누락됐습니다.", "확정된 무기 유지 정책을 반영하세요.",
                        decision_key="boss_weapon", resolution_kind="auto_fix")
    return State(run_id="repair", status="CRITIQUING", user_request="게임",
                 critic_pass_count=3, refinement={"termination": "round_budget", "cycle": 1, "round": 3, "stale": 0, "best_score": 7, "selected": True}, completed_tasks=["requirement_lock_stage", "spec_compile", "checklist_critic", "review_resolution"],
                 structured_issues=[issue.to_dict()], resolution_history=[{"issues": [issue.to_dict()]}],
                 confirmed_user_sources={"user_answer:Q1": "보스 격파 후 무기를 유지합니다."}).to_dict()


@pytest.mark.parametrize("action", ["answer", "message", "revise", "retry"])
def test_new_segment_resets_budget_without_deleting_evidence(action):
    flow = workflow()
    state = {**exhausted(), "resolution_stop": True, "diagnosed_keys": ["weapons:boss_weapon"],
             "pending_input": {"action": action}}
    fresh = {**state, **flow.prepare(state)}
    assert fresh["critic_pass_count"] == 0
    assert not fresh["resolution_stop"]
    assert fresh["diagnosed_keys"] == []
    for key in ("confirmed_user_sources", "resolution_history", "structured_issues"):
        assert fresh[key] == state[key]
    assert fresh["execution_segment"] == state["execution_segment"] + 1
    if action == "retry":
        assert "spec_compile" in allowed_tasks(fresh, flow.engine.config)
        assert "compose_candidate" not in allowed_tasks(fresh, flow.engine.config)


def test_answered_weapon_policy_waits_without_model_call(monkeypatch):
    import backend.pipeline.planner as planner

    flow = workflow()
    flow.nodes.config = flow.engine.config
    complete = Mock(side_effect=AssertionError("한도 대기에는 모델 호출이 필요하지 않습니다."))
    monkeypatch.setattr(planner, "_complete_once", complete)
    state = exhausted()
    plan = plan_next(state, flow.nodes)
    assert plan["action"] == "compose_candidate"
    assert "compose_candidate" in allowed_tasks(state, flow.engine.config)
    flow.nodes.interview.assert_not_called()
    flow.nodes.review_resolution.assert_not_called()
    complete.assert_not_called()


def test_limit_and_repeated_defect_are_separate_and_pending_questions_win():
    flow = workflow()
    state = exhausted()
    constraints = execution_constraints(state, flow.engine.config)
    assert constraints["repair_limit_reached"] and not constraints["no_progress"]
    assert plan_next({**state, "resolution_stop": True}, flow.engine)["action"] == "compose_candidate"
    pending = {**state, "blocking_questions": ["[Q2] 새 정책을 정해주세요."]}
    assert "ask_user" in allowed_tasks(pending, flow.engine.config)
    assert flow.blocked(pending)["status"] == "NEEDS_USER_INPUT"


def test_reviewed_clean_candidate_remains_available_at_limit():
    flow = workflow()
    state = exhausted()
    state["structured_issues"][0]["status"] = "resolved"
    assert "compose_candidate" in allowed_tasks(state, flow.engine.config)


def test_unanswered_decision_remains_questionable_after_review_limit():
    flow = workflow()
    state = exhausted()
    state["structured_issues"][0]["resolution_kind"] = "user_decision"
    assert "ask_user" in allowed_tasks(state, flow.engine.config)
    assert "spec_compile" not in allowed_tasks(state, flow.engine.config)


def test_limit_report_distinguishes_proposed_fix_from_executed_work():
    from backend.services.review_resolution import failure_report

    state = exhausted()
    issue = state["structured_issues"][0]
    issue.update(decision_answer_id="Q1", basis_refs=["user_answer:Q1"])
    state["resolution_history"] = [{"review_round": 1, "draft_hash": "abc", "issues": [issue]}]
    state.update(stop_reason="repair_limit", task_results=[{"action": "spec_compile", "status": "completed", "reason": "확정 근거 반영"}])
    report = failure_report(state)
    assert "제안한 보완" in report
    assert "재사용한 답변: Q1" in report
    assert "확정 근거: user_answer:Q1" in report
    assert "다음 보완:" in report
    assert "spec_compile" in report
    assert "추가 의견 없이" in report


def test_weapon_answer_is_reused_instead_of_asking_again():
    from backend.models import parse_issue_list
    from backend.services.review_questions import collect_review_questions
    from backend.services.review_resolution import decision_identity

    state = exhausted()
    issues = parse_issue_list(state["structured_issues"])
    issue = issues[0]
    issue.resolution_kind = "user_decision"
    issue.decision_question = "보스 격파 후 무기를 유지할까요?"
    state["requirement_lock_sheet"] = {"user_answers": [{"question_id": "Q1", "question": issue.decision_question,
                                                           "answer": "보스 격파 후 무기를 유지합니다."}]}
    state["review_questions"] = [{"decision_key": decision_identity(issue), "question_id": "Q1"}]
    _, pending = collect_review_questions(issues, state, 2)
    assert pending == []
    assert issue.resolution_kind == "auto_fix"
    assert issue.decision_answer_id == "Q1"
    assert "user_answer:Q1" in issue.basis_refs
    assert issue.status != "resolved"


def test_graph_wait_retry_repair_and_review(monkeypatch):
    from backend.models import RequirementLockSheet, RequirementItem
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    import backend.pipeline.agent_workflow as agent

    flow = workflow()
    state = exhausted()
    flow.nodes.spec_compile = Mock(return_value={})
    flow.nodes.checklist_critic = Mock(return_value={"critic_pass_count": 1})
    repaired = {**state["structured_issues"][0], "status": "resolved"}
    flow.nodes.review_resolution.return_value = {"structured_issues": [repaired], "refinement": {"termination": "max_score"}}
    flow.nodes.compose_candidate = Mock(return_value={})
    flow.writer = Mock()
    flow.writer.read_text.return_value = "draft"
    import hashlib
    flow._candidate_hash = lambda: hashlib.sha256(b"draft").hexdigest()
    monkeypatch.setattr("backend.server.execution_history.ExecutionHistory.graph", lambda _: {"nodes": []})

    def plan(current, _):
        if current["critic_pass_count"] >= 3:
            return {"action": "blocked", "stop_reason": "repair_limit", "reason": "횟수 소진"}
        done = current["completed_tasks"]
        if "spec_compile" not in done:
            action = "spec_compile"
        elif "review_resolution" in done:
            action = "compose_candidate" if current["structured_issues"][0]["status"] == "resolved" else "spec_compile"
        elif "checklist_critic" in done:
            action = "review_resolution"
        else:
            action = "checklist_critic"
        return {"action": action, "reason": "보완 결과 검증", "input_refs": []}

    monkeypatch.setattr(agent, "plan_next", plan)
    graph = flow.build(InMemorySaver())
    config = {"configurable": {"thread_id": "repair-retry"}}
    graph.invoke(state, config)
    saved = graph.get_state(config)
    assert saved.tasks[0].interrupts
    assert saved.values["stop_reason"] == ""
    assert "approve" in saved.values["allowed_actions"]
    flow.nodes.spec_compile.assert_not_called()
    graph.invoke(Command(resume={"action": "retry", "state": saved.values}), config)
    final = graph.get_state(config).values
    flow.nodes.spec_compile.assert_called_once()
    flow.nodes.checklist_critic.assert_called_once()
    flow.nodes.review_resolution.assert_called_once()
    assert final["allowed_actions"] == ["approve", "message", "revise", "retry"]
    assert final["confirmed_user_sources"] == state["confirmed_user_sources"]


def test_stop_diagnostic_links_proposals_to_changed_draft_reviews():
    from backend.services.review_resolution import stop_diagnostic

    state = exhausted()
    issue = state["structured_issues"][0]
    issue["required_change"] = "무기 유지 규칙 반영"
    state["resolution_history"] = [
        {"review_round": 1, "draft_hash": "a", "issues": [dict(issue)]},
        {"review_round": 2, "draft_hash": "b", "issues": [dict(issue)]},
    ]
    diagnostic = stop_diagnostic(state)
    attempts = diagnostic["issues"][0]["attempts"]
    assert "같은 결함" in attempts[0]["outcome"]
    assert "확인되지 않습니다" in attempts[1]["outcome"]
    assert "미확정" in diagnostic["cause"]
    assert attempts[0]["proposed_change"] == "무기 유지 규칙 반영"
    state["resolution_history"][1]["draft_hash"] = "a"
    assert "확인되지 않습니다" in stop_diagnostic(state)["issues"][0]["attempts"][0]["outcome"]


def test_old_terminal_diagnostic_uses_same_execution_only():
    from types import SimpleNamespace
    from backend.server.execution_history import ExecutionHistory

    history = ExecutionHistory(SimpleNamespace())
    issue = exhausted()["structured_issues"][0]
    nodes = [
        {"id": "other", "execution_id": "old", "result": {"resolution_history": [{"issues": [issue]}]}},
        {"id": "review", "execution_id": "current", "detail": {"issues": [issue]}},
        {"id": "stop", "execution_id": "current", "stage": "workflow", "status": "blocked"},
    ]
    history._load = lambda **kwargs: {"nodes": nodes}
    diagnostic = history.detail("stop")["result"]["stop_diagnostic"]
    assert diagnostic["issues"][0]["problem"] == issue["problem"]
    assert diagnostic["issues"][0]["attempts"] == []
    assert diagnostic["recording_incomplete"]
    nodes[1].pop("detail")
    assert history.detail("stop")["result"]["stop_diagnostic"]["issues"] == []


def test_terminal_diagnostic_records_only_completed_work_counts():
    from backend.server.execution_history import _safe_result

    state = exhausted()
    state.update(status="CRITICAL_BLOCKED", stop_reason="repair_limit", task_results=[
        {"action": "spec_compile", "status": "completed", "raw_response": "untrusted content"},
        {"action": "spec_compile", "status": "reused"},
        {"action": "spec_compile", "status": "failed"},
    ])
    result = _safe_result(state)
    assert result["stop_diagnostic"]["completed_work"] == [{"action": "spec_compile", "count": 1}]
    assert "untrusted content" not in str(result)
    assert "task_results" not in result
