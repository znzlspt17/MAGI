"""검토 결정 질문과 실행 오류를 실제 엔진 경계에서 구분한다."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.config import MagiConfig
from backend.engine import MagiSpecEngine
from backend.errors import InvalidStateError, ReviewValidationError
from backend.infrastructure.output_language import OutputLanguageError
from backend.models import (
    CompletionResult, InterviewResponse, IssuePacket, LockResponse, MagiState, RequirementItem,
    ReportResponse, ReviewResponse, ReviewResolutionResponse, SpecDraftResponse as SpecResponse, merge_issue_lists,
)
from backend.pipeline.builder import route_after_resolution
from backend.services.checklist_critic import ChecklistCritic
from backend.services.review_questions import collect_review_questions


def korean_decision(question="메모를 며칠 동안 보관하나요?", checklist="RETENTION-001", severity="major"):
    return dict(defect_kind='requirements_gap', resolution_reason='사용자 결정이 필요한 중요한 선택입니다.', missing_information='동작을 정할 중요한 정보가 없습니다.', decision_key="retention" if question and "보관" in question else checklist, section="## 18. Persistence / Artifact Policy", severity=severity,
                checklist_id=checklist, requirement_id="REQ-001",
                problem="메모 보관 기간이 미정입니다.", required_change="보관 기간을 사용자에게 확인해야 합니다.",
                evidence=[dict(source="draft", quote="Store notes locally.")],
                resolution_kind="user_decision", decision_question=question)


def auto_fix():
    value = korean_decision()
    value.update(defect_kind='spec_omission', resolution_reason='확정 요구사항에 따라 명세를 보완해야 합니다.', missing_information='', decision_key="VERIFY-001", resolution_kind="auto_fix", decision_question=None, checklist_id="VERIFY-001",
                 problem="완료 조건이 누락되었습니다.", required_change="이미 확정한 로컬 저장의 검증 조건을 추가하세요.")
    return value


def resolution_value(issues):
    issues = [{"resolution_kind": "auto_fix", "decision_question": None, **item} for item in issues]
    return {"resolutions": [dict(issue_id=item["issue_id"], defect_kind="requirements_gap" if item["resolution_kind"] == "user_decision" else "spec_omission",
        resolution_kind=item["resolution_kind"], resolution_reason="확정 근거와 누락 정보를 대조했습니다.",
        missing_information="사용자 동작을 결정할 정보가 없습니다." if item["resolution_kind"] == "user_decision" else "",
        decision_key=item["decision_key"], decision_question=item["decision_question"], required_change=item["required_change"],
        basis_refs=[item["requirement_id"] or "user_request"], impact="behavior" if item["resolution_kind"] == "user_decision" else "none", conflicting_source=None)
        for item in issues]}


class DecisionProvider:
    provider_name = "openai"

    def __init__(self, reviews):
        self.reviews = iter(reviews)
        self.calls = []
        self.contexts = {}

    def validate_credentials(self):
        pass

    def create_conversation(self):
        return "conv_review"

    def complete_result(self, messages, **kwargs):
        schema = kwargs["text_format"]
        self.calls.append(schema)
        for message in messages:
            if message["content"].startswith("Canonical context:\n"):
                self.contexts[schema] = json.loads(message["content"].split("\n", 1)[1])
        if schema is InterviewResponse:
            parsed = schema(request_type="feature", assumptions=[], blocking_questions=[], additional_questions=[],
                            pre_answers=[dict(question_id="PLATFORM-001", question="대상 플랫폼은 무엇인가요?", answer="Windows")])
        elif schema is LockResponse:
            answers = self.contexts[schema]["saved_answers"]
            sources = self.contexts[schema]["sources"]
            answers = [{**item, 'answer': sources[item['answer_source']].get('text', '')}
                       if 'answer_source' in item else item for item in answers]
            text = "Store notes locally."
            if any(a["answer"] == "30일" for a in answers):
                text += " Retain notes for 30 days."
            parsed = schema(request_summary="로컬 메모 앱", workflow_constraints=[], mandatory_requirements=[dict(id="REQ-001", text=text,
                source=next(key for key, item in sources.items() if item['type'] == 'user_request'), original_text="메모를 저장해주세요",
                sources=[key for key, item in sources.items() if item['type'] == 'user_answer' and any(a['question_id'] == item['question_id'] for a in answers)])],
                recommended_requirements=[], optional_requirements=[], non_scope=[], constraints=[], assumptions=[],
                acceptance_criteria_seed=["REQ-001: Verify local persistence."], unresolved_questions=[])
        elif schema is SpecResponse:
            parsed = schema(**{key: [dict(item_id="ITEM-" + key, text="Store notes locally. Verify local persistence on Windows.",
                requirement_ids=["REQ-001"] if key == "architecture" else [], decision_ids=[])]
                for key in schema.model_fields if key != "decisions"})
        elif schema is ReviewResponse:
            parsed = schema(issues=next(self.reviews))
            self.last_issues = parsed.issues
        elif schema is ReviewResolutionResponse:
            issues = [{**item, **{key: getattr(previous, key) for key in ('resolution_kind', 'decision_question')}}
                      for item in self.contexts[schema]["issues"]
                      for previous in self.last_issues if previous.checklist_id == item['checklist_id']]
            parsed = schema.model_validate(resolution_value(issues))
        else:
            parsed = ReportResponse(summary="자동 보완으로 해결하지 못했습니다.", blocking_causes=[], required_user_decisions=[], resume_conditions=[])
        return CompletionResult(text="", parsed=parsed, response_id=f"resp_review{len(self.calls)}")


def engine_for(provider):
    config = MagiConfig.default()
    config.max_critic_passes = 2
    config.web_search = "off"
    config.project_scan = False
    return MagiSpecEngine(config=config, provider=provider)


def read_state(directory):
    return json.loads((directory / "state/magi_state.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("extra, allowed", [
    ("The request cites <original_quote>록맨, 건볼트, 마이티넘버나인...</original_quote>.", True),
    ("> 사용자 원문 인용\n\nUse `한글 식별자`.\n```python\nprint('한글 코드')\n```", True),
    ("Use the player’s direction — left → right.", True),
    ("This is English. 인용 밖의 한국어 본문입니다.", False),
])
def test_approval_uses_compiler_language_contract(tmp_path, extra, allowed):
    provider = DecisionProvider([[]])
    engine = engine_for(provider)
    result = engine.generate_from_text(text="메모를 저장해주세요", output_dir=str(tmp_path))
    candidate = Path(result.approval_candidate_path)
    content = candidate.read_text(encoding="utf-8") + "\n\n" + extra + "\n"
    candidate.write_text(content, encoding="utf-8")
    calls_before = len(provider.calls)

    if allowed:
        assert engine.approve(str(tmp_path)).status == "FINALIZED"
        assert (tmp_path / "final/FINAL_AGENT_SPEC.md").read_text(encoding="utf-8") == content
    else:
        with pytest.raises(InvalidStateError, match="English-only"):
            engine.approve(str(tmp_path))
        assert read_state(tmp_path)["status"] == "PASS_PENDING_USER_APPROVAL"
        assert not (tmp_path / "final/FINAL_AGENT_SPEC.md").exists()
    assert len(provider.calls) == calls_before


def answer(record, text):
    return dict(question_id=record["question_id"], question=record["question"], answer=text)


def test_review_waits_immediately_and_resumes_lock_after_partial_answers_and_restart(tmp_path):
    first = korean_decision()
    duplicate = korean_decision(question="  메모를 며칠 동안 보관하나요 ?  ", checklist="RETENTION-TEST-001")
    second = korean_decision(question="저장 실패 시 사용자에게 어떤 안내를 하나요?", checklist="FAILURE-001", severity="minor")
    provider = DecisionProvider([[first, duplicate, second, auto_fix()], []])
    engine = engine_for(provider)
    events = []
    result = engine.generate_from_text(text="메모를 저장해주세요", output_dir=str(tmp_path), on_progress=events.append)
    assert result.status == "NEEDS_USER_INPUT"
    assert provider.calls.count(SpecResponse) == 1
    assert not any(e["state"] == "retrying" for e in events)
    state = read_state(tmp_path)
    assert state["awaiting_input_reason"] == "review"
    assert len(state["blocking_questions"]) == 2
    assert len(state["review_questions"][0]["issue_ids"]) == 2
    assert len(state["review_history"]) == 1
    assert "메모를 며칠" in Path(result.questions_path).read_text(encoding="utf-8")
    with pytest.raises(InvalidStateError):
        engine.approve(str(tmp_path))

    questions = state["review_questions"]
    before = list(provider.calls)
    result = engine.answer(str(tmp_path), answers=[answer(questions[0], "30일")])
    assert result.status == "NEEDS_USER_INPUT"
    assert provider.calls == before
    partial = read_state(tmp_path)
    assert partial["blocking_questions"] == [state["blocking_questions"][1]]
    assert partial["structured_issues"] == state["structured_issues"]
    assert partial["review_history"] == state["review_history"]
    assert partial["critic_pass_count"] == 1

    restarted = engine_for(provider)
    result = restarted.answer(str(tmp_path), answers=[answer(questions[1], "저장 실패를 화면에 표시")])
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert provider.calls[len(before):] == [LockResponse, SpecResponse, ReviewResponse]
    final = read_state(tmp_path)
    assert final["critic_pass_count"] == 1
    assert len(final["review_history"]) == 2
    assert final["review_history"][0]["issues"] == state["structured_issues"]
    saved = {a["question_id"]: a["answer"] for a in final["requirement_lock_sheet"]["user_answers"]}
    assert saved == {"PLATFORM-001": "Windows", questions[0]["question_id"]: "30일", questions[1]["question_id"]: "저장 실패를 화면에 표시"}
    assert final["blocking_questions"] == []
    assert final["awaiting_input_reason"] is None
    assert "30 days" in final["requirement_lock_sheet"]["mandatory_requirements"][0]["text"]
    assert "30 days" in Path(result.approval_candidate_path).read_text(encoding="utf-8")
    assert restarted.approve(str(tmp_path)).status == "FINALIZED"


@pytest.mark.parametrize("severity,repeated_kind", [("major", "user_decision"), ("minor", "auto_fix")])
def test_answer_does_not_resolve_issue_and_same_decision_is_not_asked_twice(tmp_path, severity, repeated_kind):
    repeated_issue = korean_decision(severity=severity)
    if repeated_kind == "auto_fix":
        repeated_issue.update(resolution_kind="auto_fix", decision_question=None)
    provider = DecisionProvider([[korean_decision(severity=severity)], [repeated_issue], []])
    engine = engine_for(provider)
    assert engine.generate_from_text(text="메모 저장", output_dir=str(tmp_path)).status == "NEEDS_USER_INPUT"
    initial = read_state(tmp_path)
    result = engine.answer(str(tmp_path), answers=[answer(initial["review_questions"][0], "30일")])
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert provider.calls.count(InterviewResponse) == 1
    state = read_state(tmp_path)
    history = state["review_history"]
    assert len(history) == 3
    repeated = history[1]["issues"][0]
    assert repeated["resolution_kind"] == "auto_fix"
    assert repeated["status"] == "open"
    if repeated_kind == "user_decision":
        assert "30일" in repeated["required_change"]
    assert repeated["decision_answer_id"] == initial["review_questions"][0]["question_id"]
    assert state["critic_pass_count"] == 2


def test_auto_fix_misses_do_not_use_error_retry_budget(tmp_path):
    provider = DecisionProvider([[auto_fix()], []])
    events = []
    result = engine_for(provider).generate_from_text(text="메모 저장", output_dir=str(tmp_path), on_progress=events.append)
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert provider.calls.count(SpecResponse) == 2
    assert not any(e["state"] == "retrying" for e in events)
    assert read_state(tmp_path)["review_questions"] == []


@pytest.mark.parametrize("recovers", [True, False])
def test_invalid_review_is_execution_error_with_three_additional_calls(tmp_path, recovers):
    invalid = korean_decision()
    invalid["evidence"] = []
    provider = DecisionProvider([[invalid], [invalid], [invalid], [] if recovers else [invalid]])
    engine = engine_for(provider)
    events = []
    if recovers:
        assert engine.generate_from_text(text="메모", output_dir=str(tmp_path), on_progress=events.append).status == "PASS_PENDING_USER_APPROVAL"
    else:
        with pytest.raises(ReviewValidationError):
            engine.generate_from_text(text="메모", output_dir=str(tmp_path), on_progress=events.append)
        assert not (tmp_path / "review/checklist_issues.json").exists()
    assert provider.calls.count(ReviewResponse) == 4
    assert provider.calls.count(SpecResponse) == 1
    assert [e["result"]["retry_attempt"] for e in events if e["state"] == "retrying"] == [1, 2, 3]


@pytest.mark.parametrize("question", [None, "Choose retention duration"])
def test_missing_or_non_korean_question_cannot_proceed(tmp_path, question):
    invalid = korean_decision()
    invalid["decision_question"] = question
    provider = DecisionProvider([[invalid]] * 4)
    with pytest.raises((ReviewValidationError, OutputLanguageError)) as caught:
        engine_for(provider).generate_from_text(text="메모", output_dir=str(tmp_path))
    assert not isinstance(caught.value, StopIteration)
    assert provider.calls.count(ReviewResponse) == 4
    assert provider.calls.count(SpecResponse) == 1


def test_questions_override_review_limit_and_minor_severity():
    issue = korean_decision(severity="minor")
    issue["issue_id"] = "I-001"
    records, pending = collect_review_questions([IssuePacket.from_dict(issue)], {}, 1)
    assert route_after_resolution(dict(structured_issues=[issue], blocking_questions=pending,
        awaiting_input_reason="review", review_questions=records, critic_pass_count=2, max_critic_passes=2)) == "await_user"


def test_legacy_issues_and_state_default_to_auto_fix():
    value = auto_fix()
    value.pop("resolution_kind")
    value.pop("decision_question")
    issue = IssuePacket.from_dict(value)
    assert issue.resolution_kind == "auto_fix"
    assert issue.decision_question is None
    state = MagiState.from_dict(dict(run_id="run", status="DRAFT", user_request="request", input_source="text", project_dir=None, output_dir="out"))
    assert state.review_questions == []
    assert state.awaiting_input_reason is None


def test_malformed_legacy_provider_review_is_not_a_spec_issue():
    from backend.models import RequirementLockSheet
    with pytest.raises(ReviewValidationError):
        ChecklistCritic().critique("draft", RequirementLockSheet(lock_id="test", request_type="feature", request_summary="메모", workflow_constraints=[], mandatory_requirements=[RequirementItem("REQ-001", "Save notes.", "user_request")]), provider_messages_fn=lambda messages: "not json")


def test_deterministic_collision_does_not_discard_user_decision():
    value = korean_decision(severity="minor")
    additional = IssuePacket.from_dict(value)
    base = deepcopy(additional)
    base.severity = "blocking"
    base.resolution_kind = "auto_fix"
    base.decision_question = None
    result = merge_issue_lists([base], [additional])
    assert len(result) == 2
    assert result[0].severity == "blocking"
    assert result[1].resolution_kind == "user_decision"
    assert result[1].problem == additional.problem


def test_new_decision_after_answers_waits_again_with_history_intact(tmp_path):
    later = korean_decision(question="백업 기능이 필요한가요?", checklist="BACKUP-001")
    provider = DecisionProvider([[korean_decision()], [later]])
    engine = engine_for(provider)
    engine.generate_from_text(text="메모 저장", output_dir=str(tmp_path))
    original = read_state(tmp_path)
    result = engine.answer(str(tmp_path), answers=[answer(original["review_questions"][0], "30일")])
    assert result.status == "NEEDS_USER_INPUT"
    state = read_state(tmp_path)
    assert len(state["review_questions"]) == 2
    assert len(state["blocking_questions"]) == 1
    assert "백업 기능" in state["blocking_questions"][0]
    assert len(state["review_history"]) == 2
    assert state["critic_pass_count"] == 1
    assert provider.calls.count(InterviewResponse) == 1


def test_existing_interview_answer_is_used_instead_of_asking_again():
    issue = IssuePacket.from_dict(korean_decision())
    issue.basis_refs = ["user_answer:RETENTION-001"]
    records, pending = collect_review_questions([issue], dict(requirement_lock_sheet={"user_answers": [
        dict(question_id="RETENTION-001", question=issue.decision_question, answer="30일")]}), 1)
    assert records == []
    assert pending == []
    assert issue.resolution_kind == "auto_fix"
    assert issue.status == "open"
    assert "30일" in issue.required_change


def test_public_state_and_execution_history_keep_question_context(tmp_path, monkeypatch):
    from backend.server.job_manager import JobManager

    provider = DecisionProvider([[korean_decision(), korean_decision(question="백업이 필요한가요?", checklist="BACKUP-001")]])
    manager = JobManager(tmp_path, engine_factory=lambda: engine_for(provider))
    monkeypatch.setattr(manager, "_submit_locked", lambda *args: None)
    try:
        created = manager.create("메모 저장")
        ident = created["id"]
        manager._run(ident, "generate", None)
        public = manager.public(ident)
        assert public["status"] == "NEEDS_USER_INPUT"
        assert public["state"]["awaiting_input_reason"] == "review"
        record = public["state"]["review_questions"][0]
        assert record["problems"] == ["메모 보관 기간이 미정입니다."]
        waiting = public["execution_graph"]["nodes"][-1]
        history = manager.step(ident, waiting["id"])
        assert history["result"]["review_questions"][0] == record
        with pytest.raises(ValueError):
            manager.action(ident, "approve", None)
        payload = [answer(record, "30일")]
        manager.action(ident, "answer", payload)
        manager._run(ident, "answer", payload)
        partial = manager.public(ident)
        assert len(partial["state"]["blocking_questions"]) == 1
        waiting = partial["execution_graph"]["nodes"][-1]
        detail = manager.step(ident, waiting["id"])
        assert len(detail["result"]["blocking_questions"]) == 1
        assert detail["result"]["review_questions"][0] == record
        manager.close()
        manager = JobManager(tmp_path, engine_factory=lambda: engine_for(provider))
        restored = manager.public(ident)
        assert restored["state"]["review_questions"] == partial["state"]["review_questions"]
        assert restored["state"]["blocking_questions"] == partial["state"]["blocking_questions"]
        assert any(item["question_id"] == record["question_id"] and item["answer"] == "30일"
                   for item in restored["state"]["saved_answers"])
    finally:
        manager.close()
