"""작업별 기준의 근거·수명·초안 연결과 기존 검토 루프의 승인 경계를 검증한다."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.errors import ReviewValidationError
from backend.models import RequirementItem, RequirementLockSheet, RubricResponse, ReviewResponse, IssuePacket
from backend.services import rubric
from backend.services.checklist_critic import ChecklistCritic
from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS, _assemble_locked_sections


class Documents:
    def __init__(self):
        self.data = {}

    def exists(self, path):
        return path in self.data

    def read_json(self, path):
        return deepcopy(self.data[path])

    def write_json(self, path, value, **kwargs):
        self.data[path] = deepcopy(value)


@pytest.fixture
def case(monkeypatch):
    sheet = RequirementLockSheet("lock", "feature", "메모", [],
        mandatory_requirements=[RequirementItem("REQ-001", "Store notes locally.", original_text="메모 저장")])
    state = {"user_request": "메모 저장", "requirement_lock_sheet": sheet.to_dict()}
    response = RubricResponse(items=[dict(rubric_id="RUB-001", requirement_id="REQ-001", category="requirement",
        basis=[dict(reference="REQ-001", quote="Store notes locally.")],
        condition="Verify local note persistence is specified.", sections=["architecture", "test_plan"])])
    complete = Mock(return_value=response)
    monkeypatch.setattr(rubric, "complete_with_usage", complete)
    docs = Documents()
    record = rubric.ensure_rubric(docs, None, "model", sheet, state)
    state["rubric"] = record
    spec = "\n\n".join(heading + "\n\nStore notes locally. Verify local persistence on Windows."
                         for heading in REQUIRED_FINAL_SPEC_HEADINGS)
    spec = _assemble_locked_sections(spec, sheet)
    verdict = dict(rubric_id="RUB-001", verdict="PASS", section="architecture", evidence_kind="quote",
                   quote="Store notes locally.", reason="명세에 저장 동작이 반영되어 있습니다.", issue_checklist_id=None)
    return SimpleNamespace(sheet=sheet, state=state, response=response, complete=complete, docs=docs,
                           record=record, spec=spec, verdict=verdict)


def review(case, **changes):
    return ReviewResponse(issues=[], rubric_verdicts=[{**case.verdict, **changes}])


@pytest.mark.parametrize("change,check", [
    ("duplicate", "rubric_identity"), ("unknown", "rubric_basis"), ("quote", "rubric_basis"),
    ("coverage", "rubric_coverage"), ("workflow", "rubric_boundary"), ("section", "rubric_basis"),
    ("own_basis", "rubric_basis"), ("blank", "rubric_basis"),
])
def test_invalid_rubric_is_rejected(case, change, check):
    response = case.response.model_copy(deep=True)
    item = response.items[0]
    if change == "duplicate": response.items.append(item.model_copy(deep=True))
    elif change == "unknown": item.requirement_id = "WF-001"
    elif change == "quote": item.basis[0].quote = "FABRICATED"
    elif change == "coverage": response.items = []
    elif change == "workflow": item.condition = "Follow WF-001."
    elif change == "section": item.sections = ["unknown"]
    elif change == "own_basis": item.basis[0].reference = "user_request"
    else: item.condition = " "
    canonical, _ = rubric.inputs(case.sheet, case.state)
    with pytest.raises(ReviewValidationError) as exc:
        rubric.validate_items(response, case.sheet, canonical)
    assert exc.value.failed_checks == [check]


def test_generation_uses_only_bound_product_inputs(case):
    payload = case.complete.call_args.args[2]
    assert not any("Draft specification" in m["content"] for m in payload)
    canonical, _ = rubric.inputs(case.sheet, case.state)
    assert canonical["confirmed_basis"]["REQ-001.original_text"] == "메모 저장"
    case.sheet.workflow_constraints = [RequirementItem("WF-001", "Use one model.", original_text="모델 하나", source="user_request")]
    canonical, _ = rubric.inputs(case.sheet, case.state)
    assert "WF-001" not in str(canonical)
    case.sheet.mandatory_requirements[0].original_text = "가짜 인용"
    canonical, _ = rubric.inputs(case.sheet, case.state)
    assert "REQ-001.original_text" not in canonical["confirmed_basis"]


def test_reuse_and_changed_confirmed_inputs_preserve_versions(case, monkeypatch):
    case.sheet.lock_id = "new-volatile-id"
    assert rubric.ensure_rubric(case.docs, None, "model", case.sheet, case.state) == case.record
    # checkpoint가 기록되기 전의 재시도에서도 저장한 생성 결과를 재사용한다.
    old_state = {**case.state, "rubric": {}}
    assert rubric.ensure_rubric(case.docs, None, "model", case.sheet, old_state) == case.record
    assert case.complete.call_count == 1
    changed = {**case.state, "confirmed_user_sources": {"user_answer:Q1": "30일"}}
    updated = rubric.ensure_rubric(case.docs, None, "model", case.sheet, changed)
    assert updated["rubric_hash"] != case.record["rubric_hash"]
    assert case.complete.call_count == 2
    assert len([p for p in case.docs.data if p.startswith("review/rubrics/")]) == 2
    monkeypatch.setattr(rubric, "POLICY_VERSION", rubric.POLICY_VERSION + 1)
    assert not rubric.current_record(updated, case.sheet, changed)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown", "quote", "section", "pass_absence", "pass_issue", "nonpass_no_issue"])
def test_invalid_evaluation_is_rejected(case, change):
    value = review(case)
    item = value.rubric_verdicts[0]
    if change == "missing": value.rubric_verdicts = []
    elif change == "duplicate": value.rubric_verdicts.append(item.model_copy())
    elif change == "unknown": item.rubric_id = "RUB-UNKNOWN"
    elif change == "quote": item.quote = "FABRICATED"
    elif change == "section": item.section = "mission"
    elif change == "pass_absence": item.evidence_kind, item.quote = "absence", ""
    elif change == "pass_issue": item.issue_checklist_id = "CHECK-1"
    else: item.verdict = "UNDETERMINED"
    with pytest.raises(ReviewValidationError):
        rubric.validate_evaluation(value, case.record, case.spec)


def failed_review(case, verdict="FAIL"):
    issue = dict(rubric_ids=["RUB-001"], defect_kind="verification_gap", resolution_reason="검증 방법이 누락됐습니다.",
        missing_information="", decision_key="RUB-001", section="test_plan", severity="major", checklist_id="RUB-001",
        problem="저장 검증 절차가 없습니다.", required_change="확정된 저장 동작을 확인하는 테스트를 보완하세요.",
        requirement_id="REQ-001", evidence=[dict(source="test_plan", quote="")])
    return ReviewResponse(issues=[issue], rubric_verdicts=[{**case.verdict, "verdict": verdict, "section": "test_plan",
        "evidence_kind": "absence", "quote": "", "issue_checklist_id": "RUB-001"}])


@pytest.mark.parametrize("verdict", ["FAIL", "UNDETERMINED"])
def test_absence_becomes_existing_required_issue_without_fake_quote(case, verdict):
    value = failed_review(case, verdict)
    evaluations = []
    issues = ChecklistCritic().critique(case.spec, case.sheet, provider_messages_fn=lambda _: value,
                                       rubric=case.record, evaluation_sink=evaluations.append)
    linked = [issue for issue in issues if "RUB-001" in issue.rubric_ids]
    assert len(linked) == 1
    assert linked[0].severity == "major" and linked[0].evidence[0].quote == ""
    assert IssuePacket.from_dict(linked[0].to_dict()).rubric_ids == ["RUB-001"]
    assert evaluations[0]["verdicts"][0]["verdict"] == verdict
    rubric.save_evaluation(case.docs, evaluations[0])
    state = {**case.state, "rubric_evaluation": evaluations[0]}
    with pytest.raises(ReviewValidationError):
        rubric.require_approval_evaluation(state, case.sheet, case.spec)


def test_deterministic_failure_survives_all_pass(case):
    broken = case.spec.replace("## 1. Mission", "## Missing Mission")
    issues = ChecklistCritic().critique(broken, case.sheet, provider_messages_fn=lambda _: review(case), rubric=case.record)
    assert any(item.checklist_id == "SEC-REQUIRED-001" for item in issues)


def test_normal_spec_does_not_gain_required_issues(case):
    issues = ChecklistCritic().critique(case.spec, case.sheet,
        provider_messages_fn=lambda _: review(case), rubric=case.record)
    assert not [item for item in issues if item.severity in {"blocking", "major"}]


def test_merged_defect_keeps_all_rubric_links():
    from backend.models import merge_issue_lists
    base = IssuePacket("I1", "architecture", "blocking", True, "CHECK", "결함", "보완", rubric_ids=["RUB-1"])
    additional = IssuePacket("I2", "architecture", "major", False, "CHECK", "같은 결함", "보완", rubric_ids=["RUB-2"])
    merged = merge_issue_lists([base], [additional])
    assert len(merged) == 1 and merged[0].severity == "blocking"
    assert merged[0].rubric_ids == ["RUB-1", "RUB-2"]


def test_valid_evaluation_is_bound_to_current_input_and_draft(case):
    value = rubric.validate_evaluation(review(case), case.record, case.spec)
    state = {**case.state, "rubric_evaluation": value}
    rubric.require_approval_evaluation(state, case.sheet, case.spec)
    for changed, spec in [({**state, "rubric_evaluation": {}}, case.spec),
                          (state, case.spec + " changed"),
                          ({**state, "revision_feedback": "정책 변경"}, case.spec)]:
        with pytest.raises(ReviewValidationError) as exc:
            rubric.require_approval_evaluation(changed, case.sheet, spec)
        assert exc.value.failed_checks == ["rubric_stale"]
    value["verdicts"][0]["quote"] = "FABRICATED"
    with pytest.raises(ReviewValidationError):
        rubric.require_approval_evaluation(state, case.sheet, case.spec)


def test_failed_generation_uses_existing_retry_budget_and_stops(case):
    from backend.pipeline.builder import _stage
    from backend.infrastructure.stage_retry import MAX_RETRIES
    case.docs.data.clear()
    case.complete.return_value = RubricResponse(items=[])
    events = []
    stage = _stage("spec_compile", lambda state: rubric.ensure_rubric(case.docs, None, "model", case.sheet, state), events.append)
    with pytest.raises(ReviewValidationError):
        stage({**case.state, "rubric": {}})
    assert case.complete.call_count == 1 + MAX_RETRIES + 1
    assert not case.docs.exists(rubric.PATH)
    assert events[-1]["state"] == "failed"
    assert events[-1]["result"]["diagnostic"]["error_stage"] == "rubric_generate"


def test_legacy_retry_rebuilds_rubric_without_erasing_user_answers(case):
    from backend.services.execution_segment import prepare_segment
    state = {**case.state, "rubric": {}, "completed_tasks": ["interview", "requirement_lock_stage", "spec_compile", "checklist_critic", "review_resolution"],
             "pending_input": {"action": "retry"}, "confirmed_user_sources": {"user_answer:Q1": "Windows"}, "critic_pass_count": 3}
    result = prepare_segment(state)
    assert result["completed_tasks"] == ["interview", "requirement_lock_stage"]
    assert result["critic_pass_count"] == 0
    assert state["confirmed_user_sources"] == {"user_answer:Q1": "Windows"}


def test_history_exposes_counts_not_model_text(case):
    from backend.application.history_projection import _safe_result, _summary
    evaluation = rubric.validate_evaluation(review(case), case.record, case.spec)
    result = _safe_result({"rubric": case.record, "rubric_evaluation": evaluation,
        "rubric_summary": {**rubric.summary(case.record, evaluation), "raw": "MODEL_RAW"}})
    assert "rubric" not in result and "rubric_evaluation" not in result
    assert "MODEL_RAW" not in str(result)
    assert result["rubric_summary"]["PASS"] == 1
    assert "충족 1" in _summary("checklist_critic", result)


def test_signature_changes_with_rubric_and_evaluation(case):
    from backend.pipeline.planner import task_signature
    before = task_signature(case.state, "compose_candidate")
    evaluation = rubric.validate_evaluation(review(case), case.record, case.spec)
    assert before != task_signature({**case.state, "rubric_evaluation": evaluation}, "compose_candidate")


def test_old_completed_journal_is_revalidated_without_changing_uncertain_call_identity():
    from backend.pipeline.agent_workflow import AgentWorkflow, task_id, digest
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.errors import InvalidStateError

    flow = AgentWorkflow(SimpleNamespace(), None, Mock(changed={}), EvidenceRegistry())
    flow.persist = Mock()
    flow.journal = Mock()
    flow.journal.get.return_value = {"result": {"old": True}}
    state = {"run_id": "job", "revision": 1, "plan_history": []}
    operation = Mock(return_value={"new": True})
    assert task_id(state, "spec_compile") == digest(["job", 1, 0, "spec_compile"])
    assert flow.durable("spec_compile", state, operation)["new"] is True
    payload = flow.journal.complete.call_args.args[1]
    assert payload["rubric_policy_version"] == rubric.POLICY_VERSION
    flow.journal.get.return_value = payload
    assert flow.durable("spec_compile", state, operation)["new"] is True
    assert operation.call_count == 1
    flow.journal.get.side_effect = InvalidStateError("uncertain call")
    with pytest.raises(InvalidStateError):
        flow.durable("spec_compile", state, operation)
    assert operation.call_count == 1


def test_new_job_shares_rubric_and_records_safe_counts(store, monkeypatch):
    from test_workflow import manager_for
    from backend.models import RubricResponse
    from backend.application.execution_history import ExecutionHistory

    manager, provider = manager_for(store, monkeypatch)
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        state = manager.workspace.state(ident)
        assert provider.calls.count(RubricResponse) == 1
        assert provider.calls.count(ReviewResponse) == 1
        assert state["rubric_evaluation"]["rubric_hash"] == state["rubric"]["rubric_hash"]
        docs = manager.workspace.documents(ident)
        rubric.require_approval_evaluation(state, RequirementLockSheet.from_dict(state["requirement_lock_sheet"]),
                                          docs.read_text("draft/approval_candidate_spec.en.md"))
        history = ExecutionHistory(docs)
        node = next(n for n in history.graph()["nodes"] if n["stage"] == "checklist_critic")
        detail = history.detail(node["id"])
        assert detail["result"]["rubric_summary"]["PASS"] == 1
        assert "rubric_evaluation" not in detail["result"]
    finally:
        manager.close()


@pytest.mark.parametrize("failure", ["generation", "evaluation"])
def test_pipeline_stops_after_shared_retry_budget_without_fallback(store, monkeypatch, failure):
    from test_workflow import manager_for
    from fakes import DecisionProvider
    from backend.models import SpecDraftResponse
    from backend.infrastructure.stage_retry import MAX_RETRIES

    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if failure == "generation" and isinstance(result.parsed, RubricResponse):
                result.parsed.items.clear()
            elif failure == "evaluation" and isinstance(result.parsed, ReviewResponse):
                result.parsed.rubric_verdicts.clear()
            return result

    manager, provider = manager_for(store, monkeypatch, Provider([[] for _ in range(MAX_RETRIES + 2)]))
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        job = manager.get(ident)
        assert job["status"] == "error"
        assert provider.calls.count(RubricResponse) == (MAX_RETRIES + 1 if failure == "generation" else 1)
        assert provider.calls.count(ReviewResponse) == (MAX_RETRIES + 1 if failure == "evaluation" else 0)
        assert provider.calls.count(SpecDraftResponse) == (1 if failure == "evaluation" else 0)
        assert manager.workspace.state(ident)["critic_pass_count"] == 0
    finally:
        manager.close()


def test_failed_check_uses_existing_repair_loop_and_reuses_rubric(store, monkeypatch):
    from test_workflow import manager_for
    from fakes import DecisionProvider, model_rubric
    from backend.models import SpecDraftResponse

    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if isinstance(result.parsed, ReviewResponse) and self.calls.count(ReviewResponse) == 1:
                rubric_id = model_rubric(messages)["items"][0]["rubric_id"]
                response = failed_review(SimpleNamespace(verdict=dict(rubric_id=rubric_id,
                    verdict="PASS", section="architecture", evidence_kind="quote", quote="Store notes locally.",
                    reason="명세의 저장 검증 방법을 확인했습니다.", issue_checklist_id=None)))
                item = response.rubric_verdicts[0]
                item.rubric_id, item.section, item.issue_checklist_id = rubric_id, "architecture", rubric_id
                issue = response.issues[0]
                issue.rubric_ids, issue.section = [rubric_id], "architecture"
                issue.checklist_id, issue.decision_key = rubric_id, rubric_id
                issue.evidence[0].source = "architecture"
                result.parsed.issues = response.issues
                result.parsed.rubric_verdicts = response.rubric_verdicts
                self.last_issues = response.issues
            return result

    manager, provider = manager_for(store, monkeypatch, Provider([[], []]))
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        assert provider.calls.count(RubricResponse) == 1
        assert provider.calls.count(SpecDraftResponse) == 2
        assert provider.calls.count(ReviewResponse) == 2
        state = manager.workspace.state(ident)
        assert state["critic_pass_count"] == 2
        assert state["review_history"][0]["issues"][0]["rubric_ids"]
        assert state["rubric_evaluation"]["verdicts"][0]["verdict"] == "PASS"
    finally:
        manager.close()


@pytest.mark.parametrize("schema", [RubricResponse, ReviewResponse])
def test_malformed_structured_response_is_retryable_without_echoing_output(schema):
    import httpx2
    from chat_model_fixture import transport
    from test_models import response
    from backend.providers.llm_provider import ChatModelProvider

    with transport(lambda request: httpx2.Response(200, json=response(content=[
        {"type": "output_text", "text": "UNTRUSTED_MODEL_TEXT", "annotations": []}]), request=request)):
        with pytest.raises(ReviewValidationError) as error:
            ChatModelProvider(api_key="fake-test-value").complete_result(
                [{"role": "user", "content": "test"}], model="gpt-6-luna", text_format=schema, conversation_id="conv_test")
    assert "UNTRUSTED_MODEL_TEXT" not in str(error.value)
    assert "UNTRUSTED_MODEL_TEXT" not in str(error.value.validation_details)
    assert error.value.stage == ("rubric_generate" if schema is RubricResponse else "checklist_critic")
