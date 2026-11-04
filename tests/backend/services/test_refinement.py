"""RubricRefine의 점수·후보 선택·재개·승인 경계를 검증한다."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib

import pytest

from backend.config import Config
from backend.errors import InvalidStateError, ReviewValidationError
from backend.models import State, ReviewResponse
from backend.services import rubric, refinement
from backend.services.execution_segment import prepare_segment
from tests.support.rubric_helpers import case, review, failed_review, Documents


class MemoryDocuments(Documents):
    def read_text(self, name):
        return self.data[name]

    def write_text(self, name, value, **kwargs):
        self.data[name] = value


@pytest.mark.parametrize("scores,reason,best_round,stale", [
    ([4, 6, 6, 5], "patience", 2, 2),
    ([4, 4, 5, 5, 6], "round_budget", 5, 0),
    ([10], "max_score", 1, 0),
    ([8, 8, 8], "patience", 1, 2),
])
def test_algorithm_counts_initial_round_and_preserves_first_best(case, scores, reason, best_round, stale):
    docs = MemoryDocuments()
    state = {**case.state, "structured_issues": [], "resolution_history": [{"issues": [], "action": "repair"}]}
    for index, score in enumerate(scores, 1):
        spec = case.spec + f"\nRound {index}"
        docs.write_text(refinement.DRAFT, spec)
        value = review(case)
        value.score = score
        state.update(critic_pass_count=index, rubric_evaluation=rubric.validate_evaluation(value, case.record, spec))
        state["refinement"] = refinement.record_round(docs, state, Config())
        # 같은 평가의 재개에서 라운드를 이중 집계하지 않는다.
        assert refinement.record_round(docs, state, Config()) == state["refinement"]
    current = state["refinement"]
    assert (current["termination"], current["best_round"], current["stale"]) == (reason, best_round, stale)
    assert current["round"] == len(scores)
    selected = refinement.restore_best(docs, state, case.sheet)
    assert docs.read_text(refinement.DRAFT).endswith(f"Round {best_round}")
    assert selected["rubric_evaluation"]["score"] == max(scores)
    rubric.require_approval_evaluation({**state, **selected}, case.sheet, docs.read_text(refinement.DRAFT))


@pytest.mark.parametrize("importance,cap", [("core", 4), ("critical", 7), ("secondary", 9)])
@pytest.mark.parametrize("verdict", ["FAIL", "UNDETERMINED"])
def test_score_caps_and_critical_failure_identity(case, importance, cap, verdict):
    record = deepcopy(case.record)
    record["items"][0]["importance"] = importance
    value = failed_review(case, verdict)
    value.score = cap
    value.critical_failures = [] if importance == "secondary" else ["RUB-001"]
    if importance == "secondary":
        value.issues[0].severity = "minor"
    rubric.validate_evaluation(value, record, case.spec)
    value.score = cap + 1
    with pytest.raises(ReviewValidationError):
        rubric.validate_evaluation(value, record, case.spec)
    value.score = cap
    value.critical_failures = ["UNKNOWN"]
    with pytest.raises(ReviewValidationError):
        rubric.validate_evaluation(value, record, case.spec)


def test_general_defect_caps_score_even_when_all_rubric_items_pass(case):
    value = review(case)
    issue = failed_review(case).issues[0].model_copy(deep=True)
    issue.rubric_ids = []
    issue.checklist_id = "GENERAL-1"
    value.issues = [issue]
    value.score = 7
    value.critical_failures = ["GENERAL-1"]
    value.revision_directives = ["명세 결함을 보완하세요."]
    rubric.validate_evaluation(value, case.record, case.spec)
    value.score = 10
    with pytest.raises(ReviewValidationError):
        rubric.validate_evaluation(value, case.record, case.spec)


def test_restore_keeps_matching_issues_resolution_and_trace(case):
    docs = MemoryDocuments()
    state = {**case.state, "resolution_history": [{"issues": [], "action": "repair"}]}
    for index, score in enumerate((4, 3, 3), 1):
        spec = case.spec + f"\nRound {index}"
        docs.write_text(refinement.DRAFT, spec)
        docs.write_json("analysis/spec_trace.json", {"round": index})
        value = failed_review(case)
        value.score = score
        state.update(critic_pass_count=index, structured_issues=[{"round": index}],
            rubric_evaluation=rubric.validate_evaluation(value, case.record, spec),
            resolution_history=[{"round": index, "issues": [], "action": "repair"}])
        state["refinement"] = refinement.record_round(docs, state, Config())
    selected = refinement.restore_best(docs, state, case.sheet)
    assert selected["structured_issues"] == [{"round": 1}]
    assert docs.read_json("review/resolution.json")["round"] == 1
    assert docs.read_json("analysis/spec_trace.json") == {"round": 1}
    docs.data[state["refinement"]["best_path"]]["spec"] += "tampered"
    with pytest.raises(InvalidStateError):
        refinement.restore_best(docs, state, case.sheet)


def test_segment_resume_and_explicit_extra_execution(case):
    state = {**case.state, "critic_pass_count": 3,
        "refinement": {"rubric_hash": case.record["rubric_hash"], "round": 3, "stale": 2,
            "cycle": 1, "best_score": 8, "best_path": "best", "best_round": 1, "termination": "patience", "selected": True},
        "pending_input": {"action": "retry"}}
    result = prepare_segment(state)
    assert result["refinement"]["best_score"] == 8
    assert result["refinement"]["best_path"] == "best"
    assert result["refinement"]["cycle"] == 2
    assert result["refinement"]["round"] == result["refinement"]["stale"] == 0
    state["refinement"]["termination"] = ""
    result = prepare_segment(state)
    assert "refinement" not in result and "critic_pass_count" not in result
    state["pending_input"] = {"action": "answer"}
    assert prepare_segment(state)["refinement"] == {}


@pytest.mark.parametrize("action", ["answer", "revise", "message"])
def test_new_input_resets_refinement_and_approval(action):
    state = {"pending_input": {"action": action}, "refinement": {"round": 2},
             "approval_acceptance": {"accepted": True}}
    result = prepare_segment(state)
    assert result["refinement"] == {}
    assert result["approval_acceptance"] == {}


def test_approval_requires_acceptance_bound_to_current_candidate_and_evaluation(case):
    from backend.engine import Engine
    docs = MemoryDocuments()
    engine = Engine(docs, None, provider=object())
    evaluation = rubric.validate_evaluation(failed_review(case), case.record, case.spec)
    issues = [item.model_dump() for item in failed_review(case).issues]
    state = State.from_dict({"run_id": "approval", "status": "PASS_PENDING_USER_APPROVAL", **case.state, "rubric_evaluation": evaluation, "structured_issues": issues})
    with pytest.raises(InvalidStateError):
        engine._validate_candidate_for_approval(case.spec, state)
    state.approval_acceptance = {"accepted": True, "candidate_hash": hashlib.sha256(case.spec.encode()).hexdigest(),
        "evaluation_hash": rubric.digest(evaluation)}
    engine._validate_candidate_for_approval(case.spec, state)
    state.blocking_questions = ["[Q1] 제품 결정을 선택하세요."]
    with pytest.raises(InvalidStateError):
        engine._validate_candidate_for_approval(case.spec, state)
    state.blocking_questions = []
    state.approval_acceptance["evaluation_hash"] = "stale"
    with pytest.raises(InvalidStateError):
        engine._validate_candidate_for_approval(case.spec, state)
    state.approval_acceptance["evaluation_hash"] = rubric.digest(evaluation)
    evaluation["draft_hash"] = "stale"
    with pytest.raises(ReviewValidationError):
        engine._validate_candidate_for_approval(case.spec, state)


def test_end_to_end_selects_best_then_explicit_approval_and_retry(store, monkeypatch):
    from tests.support.fakes import DecisionProvider
    from tests.support.workflow_helpers import manager_for
    from backend.models import SpecDraftResponse

    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if isinstance(result.parsed, ReviewResponse):
                result.parsed.score = 8 if self.calls.count(ReviewResponse) == 1 else 7
            elif isinstance(result.parsed, SpecDraftResponse):
                result.parsed.architecture[0].text += f" Candidate {self.calls.count(SpecDraftResponse)}."
            return result

    provider = Provider([[]] * 10)
    manager, _ = manager_for(store, monkeypatch, provider)
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        state = manager.workspace.state(ident)
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        assert state["refinement"]["termination"] == "patience"
        assert state["refinement"]["round"] == 3
        assert state["rubric_evaluation"]["score"] == 8
        docs = manager.workspace.documents(ident)
        assert "Candidate 1." in docs.read_text(refinement.DRAFT)
        public = manager.workspace.public(ident)["state"]["rubric_review"]
        assert public["requires_acceptance"] and public["selected_round"] == 1
        # 명시적 추가 실행은 최고점을 유지한 채 새 예산으로 시작한다.
        job = manager.get(ident)
        manager.action(ident, "retry", {}, expected_execution_id=job["execution_id"])
        manager._run(ident, "retry", {})
        state = manager.workspace.state(ident)
        assert state["refinement"]["cycle"] == 2
        assert state["refinement"]["round"] == 2
        assert state["rubric_evaluation"]["score"] == 8
        job = manager.get(ident)
        payload = {"candidate_hash": state["candidate_hash"], "evaluation_hash": rubric.digest(state["rubric_evaluation"]), "accept_remaining_issues": True}
        from backend.engine import Engine
        before_calls = len(provider.calls)
        for invalid in ({**payload, "evaluation_hash": "stale"}, {key: value for key, value in payload.items() if key != "evaluation_hash"}):
            with pytest.raises(InvalidStateError):
                Engine(docs, None, provider=provider).execute("approve", invalid)
        assert len(provider.calls) == before_calls
        manager.action(ident, "approve", payload, expected_execution_id=job["execution_id"])
        manager._run(ident, "approve", payload)
        state = manager.workspace.state(ident)
        assert manager.get(ident)["status"] == "FINALIZED"
        completed = docs.read_json(state["latest_completed"]["path"])
        assert completed["review"]["score"] == 8
        assert completed["review"]["acceptance"]["accepted"] is True
        from backend.application.execution_history import ExecutionHistory
        history = ExecutionHistory(docs)
        approval = next(item for item in reversed(history.graph()["nodes"]) if item.get("stage") == "approve")
        assert history.detail(approval["id"])["approval_review"]["score"] == 8
    finally:
        manager.close()


def test_approval_command_acceptance_is_strict_and_approve_only():
    from protocol.commands import JobCommand
    from pydantic import ValidationError
    command = JobCommand(kind="approve", job_id="j", execution_id="e", candidate_hash="c", evaluation_hash="v", accept_remaining_issues=True)
    assert command.parameters()["accept_remaining_issues"] is True
    assert command.parameters()["evaluation_hash"] == "v"
    with pytest.raises(ValidationError):
        JobCommand(kind="approve", job_id="j", execution_id="e", candidate_hash="c", accept_remaining_issues=True)
    with pytest.raises(ValidationError):
        JobCommand(kind="approve", job_id="j", execution_id="e", candidate_hash="c", accept_remaining_issues="true")
    with pytest.raises(ValidationError):
        JobCommand(kind="retry", job_id="j", execution_id="e", accept_remaining_issues=True)


def test_legacy_pending_candidate_requires_reassessment_and_can_resume_without_new_input(case, monkeypatch):
    from backend.services.refinement import needs_upgrade
    from backend.application.job_queries import JobQueries
    from tests.support.assessment_helpers import workflow
    import backend.pipeline.agent_workflow as agent
    state = {"run_id": "legacy", "status": "PASS_PENDING_USER_APPROVAL", **case.state,
        "allowed_actions": ["approve", "message", "revise"], "critic_pass_count": 3,
        "completed_tasks": ["requirement_lock_stage", "spec_compile", "checklist_critic", "review_resolution", "compose_candidate"],
        "rubric": {**case.record, "policy_version": 2}, "rubric_evaluation": {"old": True},
        "pending_input": {"action": "retry"}}
    assert needs_upgrade(state)
    assert not needs_upgrade({**state, "status": "FINALIZED"})
    access = SimpleNamespace(documents=lambda _: None, get=lambda _: {"status": state["status"]},
        read_json=lambda *_: None, read_text=lambda *_: None, state=lambda _: state)
    allowed = JobQueries(access).allowed("legacy")
    assert "retry" in allowed and "approve" not in allowed
    monkeypatch.setattr(agent, "interrupt", lambda _: {"action": "retry", "state": state})
    command = workflow().wait(state)
    assert command.goto == "prepare"
    result = prepare_segment(state)
    assert result["rubric_evaluation"] == result["refinement"] == {}
    assert result["critic_pass_count"] == 0
    assert result["completed_tasks"] == ["requirement_lock_stage"]


def test_execution_limit_before_selection_preserves_finished_rounds(case):
    state = {**case.state, "critic_pass_count": 5, "pending_input": {"action": "retry"},
        "refinement": {"termination": "round_budget", "round": 5, "cycle": 1, "selected": False}}
    result = prepare_segment(state)
    assert "refinement" not in result
    assert "critic_pass_count" not in result


def test_public_review_only_exposes_structured_allowlisted_fields(case):
    from backend.access.service import user_payload
    evaluation = rubric.validate_evaluation(review(case), case.record, case.spec)
    evaluation["raw"] = "MODEL_RAW"
    case.record["items"][0]["basis"][0]["raw"] = "MODEL_RAW"
    result = user_payload({"state": {"rubric_review": refinement.public_review({**case.state,
        "rubric_evaluation": evaluation, "structured_issues": []})}})
    public = result["state"]["rubric_review"]
    assert public["score"] == 10
    assert public["items"][0]["condition"]
    assert public["items"][0]["verdict"] == "PASS"
    assert "MODEL_RAW" not in str(result)


def test_legacy_approval_retry_reaches_graph_instead_of_returning_unchanged(case, monkeypatch):
    from unittest.mock import Mock
    from backend.engine import Engine
    from backend.pipeline.agent_workflow import AgentWorkflow
    state = State.from_dict({"run_id": "legacy", "status": "PASS_PENDING_USER_APPROVAL", **case.state,
        "allowed_actions": ["approve", "message", "revise"], "workflow_schema": 1,
        "rubric": {**case.record, "policy_version": 2}})
    docs = MemoryDocuments()
    docs.workflow_snapshot = lambda: SimpleNamespace(next=("wait",), tasks=[SimpleNamespace(interrupts=True)])
    docs.write_json("evidence/evidence_registry.json", {})
    engine = Engine(docs, None, provider=object())
    engine.load = lambda: state
    run = Mock(return_value=state)
    monkeypatch.setattr(AgentWorkflow, "run", run)
    engine.execute("retry", {})
    run.assert_called_once()
