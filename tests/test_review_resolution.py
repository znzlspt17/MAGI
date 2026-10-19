"""검토 분류와 독립적인 해결 판단·진단 예산·영속화를 검증한다."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest

from backend.config import MagiConfig
from backend.errors import InvalidStateError, MagiError, ReviewValidationError
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.knowledge.runtime import read_artifacts
from backend.models import CompletionResult, IssuePacket, ReportResponse, ReviewResolutionResponse, ReviewResponse
from backend.pipeline.builder import _stage
from backend.pipeline.stages.review_resolution_stage import ReviewResolutionStage
from backend.services.review_questions import collect_review_questions
from backend.services.review_resolution import confirmed_basis, defect_identity, validate_resolutions
from test_conversation_structured import transport, packet
from test_review_decisions import DecisionProvider, auto_fix, engine_for, korean_decision, read_state, resolution_value
from test_spec_block_contract import locked


def issue(**changes):
    value = auto_fix()
    value.update(issue_id="ISSUE-001", decision_key="dash-reuse", **changes)
    return IssuePacket.from_dict(value)


def state_for(item):
    return dict(user_request="대시 게임", requirement_lock_sheet=locked().to_dict(), structured_issues=[item.to_dict()],
                critic_pass_count=1, max_critic_passes=3, review_history=[dict(issues=[item.to_dict()])])


class ResolutionProvider:
    provider_name = "openai"

    def __init__(self, handler=None):
        self.handler = handler or (lambda context: resolution_value(context["issues"]))
        self.context = None
        self.calls = []

    def create_conversation(self):
        return "conv_resolution"

    def complete_result(self, messages, **kwargs):
        assert kwargs["text_format"] is ReviewResolutionResponse
        for message in messages:
            if message["content"].startswith("Canonical context:\n"):
                self.context = json.loads(message["content"].split("\n", 1)[1])
        self.calls.append(deepcopy(self.context))
        value = self.handler(self.context)
        return CompletionResult(text="", parsed=ReviewResolutionResponse.model_validate(value), response_id="resp_resolution")


def stage_for(tmp_path, provider):
    writer = ArtifactWriter(tmp_path)
    writer.write_text("draft/approval_candidate_spec.en.md", "Store notes locally. Dash inputs during cooldown are ignored.", overwrite=True)
    context = SimpleNamespace(writer=writer, provider=provider, config=MagiConfig.default())
    return ReviewResolutionStage(context)


@pytest.mark.parametrize("case,confirmed,expected", [
    ("dash-reuse", "Dash cooldown lasts 0.5 seconds.", "user_decision"),
    ("dash-reuse", "After cooldown, the next key press starts a new dash.", "auto_fix"),
])
def test_same_defect_uses_confirmed_basis_instead_of_model_proposals(tmp_path, case, confirmed, expected):
    item = issue()
    item.decision_key = case
    state = state_for(item)
    state["requirement_lock_sheet"]["mandatory_requirements"][0]["text"] = confirmed
    original = deepcopy(state["requirement_lock_sheet"])
    def handler(context):
        assert context["confirmed_basis"]["REQ-001"] == confirmed
        # 모의 제공자도 초안 제안 대신 실제 확정 근거로 분류한다.
        result = resolution_value(context["issues"])
        row = result["resolutions"][0]
        row.update(resolution_kind=expected, defect_kind="requirements_gap" if expected == "user_decision" else "verification_gap",
                   missing_information="재사용 동작 또는 정확한 체력을 정할 정보가 없어 사용자 동작이 달라집니다." if expected == "user_decision" else "",
                   impact="behavior" if expected == "user_decision" else "none",
                   decision_question="원하는 동작과 수치를 정해주시겠어요?" if expected == "user_decision" else None)
        return result
    provider = ResolutionProvider(handler)
    result = stage_for(tmp_path, provider)(state)
    assert result["structured_issues"][0]["resolution_kind"] == expected
    assert bool(result["blocking_questions"]) == (expected == "user_decision")
    assert state["requirement_lock_sheet"] == original
    assert result["resolution_history"][0]["draft_hash"]
    assert "review/resolution.json" in read_artifacts(tmp_path)


def test_diagnosis_happens_once_and_does_not_reset_budget(tmp_path):
    provider = ResolutionProvider()
    stage = stage_for(tmp_path, provider)
    state = state_for(issue())
    for count in (1, 2, 3):
        state["critic_pass_count"] = count
        state["structured_issues"][0].update(problem=f"표현이 바뀐 동일 결함 {count}", severity="blocking" if count == 2 else "major")
        state.update(stage(state))
    assert len(provider.calls) == 2
    assert provider.calls[0]["diagnose_keys"] == []
    assert provider.calls[1]["diagnose_keys"] == [defect_identity(issue())]
    assert state["critic_pass_count"] == 3 and state["resolution_stop"]
    assert len(state["resolution_history"]) == 3
    assert state["resolution_history"][-1]["action"] == "stop"


@pytest.mark.parametrize("bad", ["workflow_basis", "no_impact", "no_missing", "wrong_key", "duplicate"])
def test_resolution_rejects_false_evidence_and_unnecessary_questions(bad):
    item = issue(resolution_kind="user_decision", decision_question="재사용을 허용하나요?")
    value = resolution_value([item.to_dict()])
    row = value["resolutions"][0]
    if bad.endswith("basis"):
        row["basis_refs"] = [{"unknown_basis": "REQ-MISSING", "workflow_basis": "WF-001", "assumption_basis": "ASM-001"}[bad]]
    if bad == "no_impact": row["impact"] = "none"
    if bad == "no_missing": row["missing_information"] = ""
    if bad == "wrong_key": row["decision_key"] = "changed-topic"
    if bad == "duplicate": value["resolutions"].append(dict(row))
    state = state_for(item)
    with pytest.raises(ReviewValidationError):
        validate_resolutions(ReviewResolutionResponse.model_validate(value), [item],
            confirmed_basis(state, state["requirement_lock_sheet"]), [], state)


def test_decision_keys_survive_changed_question_and_new_feedback_allows_reconfirmation():
    first = IssuePacket.from_dict(dict(korean_decision(), issue_id="I1"))
    records, _ = collect_review_questions([first], {}, 1)
    question_id = records[0]["question_id"]
    state = dict(review_questions=records, requirement_lock_sheet={"user_answers": [
        dict(question_id=question_id, question=first.decision_question, answer="30일")]},
        confirmed_user_sources={"user_answer:" + question_id: "30일"}, user_request="메모")
    changed = IssuePacket.from_dict(dict(korean_decision(question="보관할 날짜 수를 알려주세요"), issue_id="I2"))
    changed.decision_key = first.decision_key
    _, pending = collect_review_questions([changed], state, 2)
    assert pending == [] and changed.decision_answer_id == question_id
    assert changed.missing_information == "" and changed.defect_kind == "spec_omission"
    state["revision_feedback"] = "기존 30일 결정을 취소하고 새 보관 기간을 정하고 싶습니다."
    value = resolution_value([first.to_dict()])
    value["resolutions"][0].update(defect_kind="confirmed_conflict", conflicting_source="user_feedback", basis_refs=["user_feedback"])
    reconfirm = validate_resolutions(ReviewResolutionResponse.model_validate(value), [first],
        confirmed_basis(state, {}), records, state)
    new_records, pending = collect_review_questions([first], state, 3, reconfirm_keys=reconfirm)
    assert len(pending) == 1 and new_records[-1]["question_id"] != question_id
    state["review_questions"] = new_records
    state["confirmed_user_sources"]["user_answer:" + new_records[-1]["question_id"]] = "60일"
    with pytest.raises(ReviewValidationError):
        validate_resolutions(ReviewResolutionResponse.model_validate(value), [first], confirmed_basis(state, {}), new_records, state)


def test_non_validation_errors_never_replay_provider_calls():
    error = TypeError("invalid provider result")
    callback = Mock(side_effect=error)
    with pytest.raises(type(error)):
        _stage("review_resolution", callback, None)({})
    assert callback.call_count == 1


def test_sdk_resolution_contract_and_shared_validation_retry_budget(tmp_path):
    from backend.providers.llm_provider import OpenAIProvider
    requests = []
    item = issue()
    state = state_for(item)
    def handle(request):
        sent = json.loads(request.content)
        requests.append(sent)
        value = resolution_value([item.to_dict()])
        if len(requests) < 4:
            value["resolutions"][0]["basis_refs"] = ["WF-001"]
        return httpx2.Response(200, json=packet(value, "resp_resolution" + str(len(requests))))
    stage = stage_for(tmp_path, OpenAIProvider(api_key="fake-test-value"))
    with transport(handle):
        result = _stage("review_resolution", stage, None)(state)
    assert len(requests) == 4
    assert result["blocking_questions"] == []
    schema = requests[0]["text"]["format"]["schema"]
    assert "resolution_reason" in schema["$defs"]["ResolutionItem"]["required"]
    assert requests[0]["input"][0]["role"] == "developer"
    assert all(request["conversation"] == "conv_test1" for request in requests)


def test_default_three_reviews_and_report_need_no_extra_model(tmp_path):
    assert MagiConfig.default().max_critic_passes == 3
    provider = DecisionProvider([[auto_fix()], [auto_fix()], [auto_fix()]])
    engine = engine_for(provider)
    engine.config.max_critic_passes = 3
    result = engine.generate_from_text(text="메모", output_dir=str(tmp_path))
    assert result.status == "CRITICAL_BLOCKED"
    state = read_state(tmp_path)
    assert provider.calls.count(ReviewResponse) == 3
    assert provider.calls.count(ReviewResolutionResponse) == 2
    assert len(state["resolution_history"]) == 3
    assert state['blocking_questions'] == [] and provider.calls.count(ReportResponse) == 0
    report = (tmp_path / "critical/CRITICAL_REPORT.ko.md").read_text(encoding="utf-8")
    assert "진단 후에도 동일 결함" in report and "사용자 요구사항 부족으로 판정한 결과가 아닙니다" in report


def test_old_review_contract_is_rejected_before_provider_call_without_rewriting(tmp_path):
    from backend.models import MagiState
    provider = DecisionProvider([])
    old_issue = issue().to_dict()
    del old_issue["decision_key"]
    state = MagiState(run_id="old", status="CRITICAL_BLOCKED", user_request="메모", input_source="text",
        project_dir=None, output_dir=str(tmp_path), structured_issues=[old_issue])
    writer = ArtifactWriter(tmp_path)
    writer.write_json("state/magi_state.json", state.to_dict())
    before = writer.path("state/magi_state.json").read_bytes()
    with pytest.raises(InvalidStateError, match="Start a new generation"):
        engine_for(provider).status(str(tmp_path))
    assert provider.calls == [] and before == writer.path("state/magi_state.json").read_bytes()


def test_diagnosed_question_resumes_after_restart_then_can_be_approved(tmp_path):
    from dataclasses import replace
    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if kwargs["text_format"] is ReviewResolutionResponse and self.contexts[ReviewResolutionResponse]["diagnose_keys"]:
                value = result.parsed.model_dump()
                value["resolutions"][0].update(resolution_kind="user_decision", defect_kind="requirements_gap",
                    missing_information="반복 사용 조건이 정해지지 않아 사용자 동작이 달라집니다.",
                    impact="behavior", decision_question="쿨다운 뒤 바로 다시 사용할 수 있나요?")
                result = replace(result, parsed=ReviewResolutionResponse.model_validate(value))
            return result
    provider = Provider([[auto_fix()], [auto_fix()], []])
    engine = engine_for(provider)
    engine.config.max_critic_passes = 3
    events = []
    result = engine.generate_from_text(text="메모", output_dir=str(tmp_path), on_progress=events.append)
    assert result.status == "NEEDS_USER_INPUT"
    original = read_state(tmp_path)
    assert original["critic_pass_count"] == 2 and original["diagnosed_keys"]
    assert original['awaiting_input_reason'] == 'review' and len(original['blocking_questions']) == 1
    question = original['review_questions'][0]
    assert question['requirement_ids'] == ['REQ-001'] and question['missing_information'] and question['resolution_reasons']
    question_id = original["review_questions"][0]["question_id"]
    restarted = engine_for(provider)
    result = restarted.answer(str(tmp_path), answers=[dict(question_id=question_id, answer="쿨다운 뒤 바로 재사용합니다.")])
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    state = read_state(tmp_path)
    assert state["critic_pass_count"] == 1 and state["diagnosed_keys"] == []
    assert len(state["resolution_history"]) == 3
    assert "쿨다운 뒤" in state["confirmed_user_sources"]["user_answer:" + question_id]
    assert provider.calls.count(ReviewResolutionResponse) == 2
    assert any(event["stage"] == "review_resolution" for event in events)
    assert restarted.approve(str(tmp_path)).status == "FINALIZED"


def test_resolution_checkpoint_survives_a_later_provider_failure(tmp_path):
    from backend.models import SpecDraftResponse
    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            if kwargs["text_format"] is SpecDraftResponse and self.calls.count(SpecDraftResponse) == 1:
                raise MagiError("OpenAI request failed.")
            return super().complete_result(messages, **kwargs)
    provider = Provider([[auto_fix()]])
    with pytest.raises(MagiError, match="OpenAI request failed"):
        engine_for(provider).generate_from_text(text="메모", output_dir=str(tmp_path))
    state = read_state(tmp_path)
    assert len(state["resolution_history"]) == 1 and state["critic_pass_count"] == 1
    assert (tmp_path / "draft/approval_candidate_spec.en.md").exists()
    assert state["resume_stage"] == "spec_compile"


def test_failed_later_review_recovers_the_last_resolved_draft(tmp_path):
    from backend.models import LockResponse, SpecDraftResponse
    from backend.services.review_resolution import text_hash
    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            schema = kwargs["text_format"]
            if schema is ReviewResponse and self.calls.count(ReviewResponse) == 2:
                raise MagiError("OpenAI request failed.")
            result = super().complete_result(messages, **kwargs)
            if schema is SpecDraftResponse:
                result.parsed.mission[0].text = f"Build revision {self.calls.count(SpecDraftResponse)}."
            if schema is LockResponse:
                sources = self.contexts[schema]["sources"]
                result.parsed.mandatory_requirements[0].sources.extend(key for key, item in sources.items() if 'user_feedback' in item.get('roles', [item['type']]))
            return result
    provider = Provider([[], [auto_fix()]])
    engine = engine_for(provider)
    assert engine.generate_from_text(text="메모", output_dir=str(tmp_path)).status == "PASS_PENDING_USER_APPROVAL"
    feedback = tmp_path / "feedback.txt"
    feedback.write_text("로컬 저장 테스트를 보완해주세요.", encoding="utf-8")
    with pytest.raises(MagiError, match="OpenAI request failed"):
        engine.revise(output_dir=str(tmp_path), feedback_path=str(feedback))
    restored = (tmp_path / "draft/approval_candidate_spec.en.md").read_text(encoding="utf-8")
    assert "Build revision 2." in restored and "Build revision 3." not in restored
    assert read_state(tmp_path)["resolution_history"][-1]["draft_hash"] == text_hash(restored)
