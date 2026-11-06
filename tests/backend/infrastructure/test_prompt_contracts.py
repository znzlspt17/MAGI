"""실제 단계 메시지와 제공자 지침 조합에서 공통 계약을 검증한다."""

import json
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.config import Config
from backend.infrastructure.prompt_context import prepare_context
from backend.infrastructure.provider_request import stage_instructions
from backend.models import InterviewResult, IssuePacket, RequirementItem, RequirementLockSheet


def fixed_messages():
    from backend.services.interviewer import _build_messages as interview_messages
    from backend.services.requirement_lock_builder import _build_messages as lock_messages
    from backend.services.checklist_critic import _build_messages as critic_messages
    from backend.services.spec_compiler import SpecCompiler
    from backend.services.rubric import inputs
    from backend.infrastructure.prompt_messages import messages
    from backend.infrastructure.prompts import load_prompt
    from backend.pipeline.tasks import WorkflowTasks

    sheet = RequirementLockSheet("fixed", "feature", "메모 저장", [],
        mandatory_requirements=[RequirementItem("REQ-001", "메모를 로컬에 저장합니다.", original_text="메모 저장")])
    request = "메모 저장"
    state = {"user_request": request, "requirement_lock_sheet": sheet.to_dict(),
             "structured_issues": [IssuePacket("I1", "test_plan", "major", False, "TEST-COVER",
                 "저장 검증 누락", "저장 검증을 추가하세요.", requirement_id="REQ-001").to_dict()]}
    manifest = {"files": [], "file_count": 0}
    compiler = SpecCompiler(config=Config(), provider=None, skills=None)
    result = {
        "interview": interview_messages(request, manifest, [], [], state),
        "requirement_lock": lock_messages(state, manifest, InterviewResult("feature", [], []), request),
        "spec_compile": compiler._build_messages(sheet, manifest, [], user_request=request,
            previous_spec="", revision_feedback="", revision_history=[]),
        "checklist_critic": critic_messages("Draft", sheet, user_request=request,
            previous_issues=[], revision_feedback="", revision_history=[]),
        "rubric_generate": messages(load_prompt("rubric_generate"), "", json.dumps(inputs(sheet, state)[0], ensure_ascii=False)),
    }

    class Captured(Exception):
        pass

    def capture(writer, provider, payload, **kwargs):
        result["review_resolution"] = payload
        raise Captured()

    tasks = object.__new__(WorkflowTasks)
    tasks.writer = SimpleNamespace(read_text=lambda _: "Draft")
    tasks.provider, tasks.config = None, Config()
    with patch("backend.pipeline.tasks.complete_with_usage", capture):
        try:
            tasks.review_resolution(state)
        except Captured:
            pass
    return result


def assembled_instructions():
    return {stage: stage_instructions(prepare_context(None, payload, stage)[0], stage)
            for stage, payload in fixed_messages().items()}


STAGES = ("checklist_critic", "interview", "requirement_lock", "review_resolution", "rubric_generate", "spec_compile")


def test_stage_rules_are_integrated_in_four_sections():
    from backend.infrastructure.prompts import load_prompt
    for name in ("rubric_generate", "compiler", "checklist_critic", "review_resolution"):
        headings = re.findall(r"^## (.+)$", load_prompt(name), re.MULTILINE)
        assert headings[:4] == ["역할", "판단", "출력", "예외"]
        assert headings[4:] == (["질문 계약"] if name in {"checklist_critic", "review_resolution"} else [])


@pytest.mark.parametrize("stage", STAGES)

def test_question_and_language_contracts_are_composed_once_for_relevant_stages(stage):
    from backend.infrastructure.output_language import LANGUAGE_RULES
    from backend.infrastructure.prompts import PROMPT_DIR

    text = assembled_instructions()[stage]
    question = (PROMPT_DIR / "_question_contract.md").read_text(encoding="utf-8").strip()
    expected = int(stage in {"interview", "checklist_critic", "review_resolution"})
    assert text.count(question) == expected
    assert text.count(LANGUAGE_RULES[stage]) == 1
    assert re.search(r"[가-힣]", text)
    assert all(text.count(heading) == 1 for heading in ("## 역할", "## 판단", "## 출력", "## 예외"))


def test_shared_question_advice_does_not_become_confirmation():
    for stage in ("interview", "checklist_critic", "review_resolution"):
        text = assembled_instructions()[stage]
        assert all(term in text for term in ("single_choice", "multiple_choice", "options=[]", "Other",
            "영향과 가정", "recommendation", "null", "표시용 조언",
            "선택, 제출, 사용자 인용 또는 승인이 아닙니다", "확정 결정으로 재사용하지 마세요"))
    text = assembled_instructions()["review_resolution"]
    assert "decision_form=null" in text
    assert "질문과 decision_form" in text


def test_interview_instructions_focus_on_agent_implementation_decisions():
    text = assembled_instructions()["interview"]
    assert "코딩 에이전트가 개발을 진행할 구현 명세" in text
    assert "팀 규모·개발 경험·개발 일정·제작 예산" in text
    assert "일반적인 필수 질문으로 묻거나 명세 작성을 막지 마세요" in text
    assert "기능·품질·배포·완료 기준" in text
    assert "사용자가 명시한" in text and "운영 비용" in text
    assert "AI 제품이라고 가정하지 말고" in text


def test_retry_keeps_one_language_contract_without_changing_retry_budget():
    from backend.infrastructure.output_language import LANGUAGE_RULES, OutputLanguageError
    from backend.infrastructure.stage_retry import retry_messages, MAX_RETRIES
    payload = retry_messages(fixed_messages()["checklist_critic"], stage="checklist_critic", attempt=1,
                             error=OutputLanguageError(["problem: ko"]))
    prepared, _ = prepare_context(None, payload, "checklist_critic")
    instructions = stage_instructions(prepared, "checklist_critic")
    dynamic = "\n".join(item["content"] for item in prepared if item["role"] not in {"system", "developer"})
    assert (instructions + dynamic).count(LANGUAGE_RULES["checklist_critic"]) == 1
    retry = json.loads(next(item["content"].split("\n", 1)[1] for item in prepared
                            if item["content"].startswith("단계 재시도 문맥:\n")))
    assert retry["max_retries"] == MAX_RETRIES == 3
    assert retry["validation_failures"] == ["problem: ko"]


def test_source_contract_keeps_selected_history_conditions_and_actor_without_duplicate_advice():
    from backend.infrastructure.prompt_context import REFERENCE_RULES
    for stage, text in assembled_instructions().items():
        if stage == "rubric_generate":
            assert REFERENCE_RULES not in text  # 이 단계는 S/K가 아닌 제품 근거를 직접 사용한다.
            continue
        assert text.count(REFERENCE_RULES) == 1
        assert all(term in text for term in ("original_actor", "조건", "actor=llm", "사용자 직접 인용이 아닙니다",
            "명시적으로 선택된 프로젝트 결정만", "다른 이력이나 이유를 확정 사실로 승격하지 마세요", "인터뷰나 검토에서 해결"))
        assert "Historical search results are reference material" not in text


def test_compiler_retains_block_trace_and_implementation_order_contracts():
    text = assembled_instructions()["spec_compile"]
    assert all(term in text for term in ("out_of_scope는 []", "LOCKED-", "spec_links",
        "독립적인 Markdown 목록 항목 하나씩", "일반 설명, 코드와 원문 인용",
        "고유하고 안정적인 item_id", "가정:", "basis_refs", "actor=llm", "acceptance_criteria_seed",
        "spec_item_ids", "completion_item_ids", "depends_on", "순환", "비필수 작업",
        "실행을 주장하거나", "workflow_constraints", "rubric ID와 판정"))


def test_critic_has_one_consistent_absence_contract_and_keeps_general_review():
    text = assembled_instructions()["checklist_critic"]
    assert all(term in text for term in ("일반 결함 검토", "일반 검토를 대체하지 않습니다", "유일한 빈 인용 예외",
        "연결된 rubric의 부재", "evidence_kind=absence", 'quote=""', "absence는 PASS가 될 수 없습니다", "정확히 하나의 이슈",
        "rubric_ids", "같은 결함", "초안에 반영되어야", "Workflow 제약", "non_scope"))
    assert "Every issue, including structural issues, must include" not in text


def test_requirement_and_resolution_keep_confirmation_and_requestion_boundaries():
    texts = assembled_instructions()
    assert all(term in texts["requirement_lock"] for term in ("actor=user", "정확한 인용", "actor=llm",
        "근거만 기록", "없으면", "unresolved_questions=[]", "이전 필수 ID", "공통 출처", "WF-*",
        "pre_answer만으로", "고위험 가정을 승인하지 마세요", "확정 선택이 아닙니다"))
    assert all(term in texts["review_resolution"] for term in ("confirmed_basis", "allowed_resolution_refs.basis_refs",
        "새로운 현재 사용자 피드백", "기존 답변 결정", "conflicting_source=null", "diagnose_keys",
        "final_assessment=true", "ask_user", "추가 수리나 중단 명령이 아닌 평가", "재시도가 늘어나지 않습니다",
        "rubric·모델 실패", "missing_information=\"\""))


def test_interview_and_rubric_keep_material_choice_and_scope_boundaries():
    texts = assembled_instructions()
    assert all(term in texts["interview"] for term in ("실질적인 영향을 미치는", "정규화된 질문 문구",
        "ask_user", "stop_reason", "확정 답변", "추론한 pre_answers", "제품 결정이 아닙니다"))
    assert all(term in texts["rubric_generate"] for term in ("모든 필수 요구사항", "제품 제약",
        "optional/recommended", "non_scope", "해당 요구사항 ID", "보조 근거",
        "의무나 선호 아키텍처를 추가", "명시되지 않은 중요한 결정", "WF-*"))


@pytest.mark.parametrize("identifier", ["", "../compiler", "..\\compiler", "/compiler"])
def test_composed_loader_preserves_path_validation(identifier):
    from backend.errors import Error
    from backend.infrastructure.prompts import load_prompt
    with pytest.raises(Error):
        load_prompt(identifier)


def test_unused_report_prompt_removed_but_reporter_remains_deterministic():
    from backend.infrastructure.prompts import PROMPT_DIR
    from backend.services.critical_reporter import CriticalReporter
    from unittest.mock import Mock
    assert not (PROMPT_DIR / "critical_reporter.md").exists()
    with patch("backend.services.review_resolution.failure_report", return_value="report") as report:
        assert CriticalReporter(skills=SimpleNamespace(assert_allowed=Mock())).generate({}) == "report"
    report.assert_called_once_with({})


def section_text(instructions, name):
    return instructions.split("## " + name + "\n", 1)[1].split("\n## ", 1)[0]


def test_rubric_and_review_outputs_describe_the_actual_schemas():
    from backend.models import RubricItem, ReviewResponse, RubricVerdict
    texts = assembled_instructions()
    generation = section_text(texts["rubric_generate"], "출력")
    assert set(RubricItem.model_fields) <= set(re.findall(r"[A-Za-z_]+", generation))
    evaluation = section_text(texts["checklist_critic"], "출력")
    assert set(ReviewResponse.model_json_schema()["properties"]) <= set(re.findall(r"[A-Za-z_]+", evaluation))
    judgment = section_text(texts["checklist_critic"], "판단")
    assert all(term in judgment for term in ("실제 심각도", "실질적인 영향", "importance", "severity", "UNDETERMINED"))
    assert {int(value) for value in re.findall(r"상한(?:은|이) (\d+)", judgment)} == {4, 7, 9}
    assert "모든 항목 PASS와 이슈 0개" in judgment
    assert "secondary는 minor도 허용" in RubricVerdict.model_fields["issue_checklist_id"].description


def test_optional_behavior_and_stage_authority_boundaries():
    texts = assembled_instructions()
    for stage in ("rubric_generate", "checklist_critic"):
        assert "선택되지 않은 optional 기능의 부재는 실패가 아닙니다" in texts[stage]
    generation = section_text(texts["rubric_generate"], "역할")
    assert "후보를 검토하거나 채점하고" in generation
    compiler = section_text(texts["spec_compile"], "판단")
    assert all(name in compiler for name in ("초기 생성", "수정 시", "검토 이슈", "근거 우선순위", "하위 조언"))
    resolution = section_text(texts["review_resolution"], "역할")
    assert all(name in resolution for name in ("confirmed_basis", "다시 채점", "판정", "검토 예산"))
    reviewer = section_text(texts["checklist_critic"], "예외")
    assert "앱은 라운드 예산" in reviewer
    assert "사용자 승인이나 실행을 허가하지 않습니다" in reviewer
    from backend.pipeline.planner import POLICY
    assert re.findall(r"^## (.+)$", POLICY, re.MULTILINE) == ["역할", "판단", "출력", "예외"]
    assert "allowed_actions" in POLICY
    assert "자동 승인" in POLICY


def test_compiler_preserves_resolved_issues_and_projects_verifier_feedback():
    from backend.services.spec_compiler import SpecCompiler
    sheet = RequirementLockSheet("fixed", "feature", "메모 저장", [],
        mandatory_requirements=[RequirementItem("REQ-001", "메모를 로컬에 저장합니다.")])
    issue = IssuePacket("I1", "test_plan", "minor", False, "SECONDARY", "문서 보완", "확정 근거로 보완하세요.",
        requirement_id="REQ-001", resolution_kind="auto_fix", basis_refs=["REQ-001", "user_request"],
        resolution_reason="이미 확정된 동작입니다.", defect_kind="spec_omission")
    resolved = IssuePacket.from_dict({**issue.to_dict(), "issue_id": "RESOLVED", "status": "resolved"})
    feedback = {"score": 9, "score_reason": "부차적인 보완이 필요합니다.", "critical_failures": [],
        "verdicts": [{"rubric_id": "RUB-1", "verdict": "FAIL", "reason": "설명이 부족합니다."}],
        "revision_directives": ["해당 설명을 보완하세요."],
        "issues": [{"problem": "OUTDATED_REVIEWER_ISSUE", "resolution_kind": "user_decision"}], "raw": "MODEL_RAW"}
    compiler = SpecCompiler(config=Config(), provider=None, skills=None)
    payload = compiler._build_messages(sheet, {}, [issue, resolved], user_request="메모 저장", previous_spec="Previous draft",
        revision_feedback="", revision_history=[], rubric={"items": [], "latest_evaluation": feedback})
    prepared, _ = prepare_context(None, payload, "spec_compile")
    sections = {item["content"].split("\n", 1)[0]: item["content"].split("\n", 1)[1]
        for item in prepared if "\n" in item["content"] and item["role"] == "user"}
    assert "Must-fix issues:" not in sections
    issues = json.loads(sections["검토 이슈:"])
    assert len(issues) == 1 and issues[0]["severity"] == "minor"
    assert issues[0]["resolution_kind"] == "auto_fix" and issues[0]["defect_kind"] == "spec_omission"
    assert issues[0]["required_change"] == issue.required_change
    assert issues[0]["resolution_reason"] == issue.resolution_reason
    basis = issues[0]["basis_refs"]
    assert "REQ-001" in basis and "user_request" not in basis
    assert any(re.fullmatch(r"S[1-9]\d*", ref) for ref in basis)
    actual = json.loads(sections["최신 검증 의견:"])
    assert actual == {key: feedback[key] for key in ("score", "score_reason", "critical_failures", "verdicts", "revision_directives")}
    assert "OUTDATED_REVIEWER_ISSUE" not in str(prepared) and "MODEL_RAW" not in str(prepared)
    assert "Previous draft" in sections["보존하고 수정할 현재 초안:"]
    initial = compiler._build_messages(sheet, {}, [], user_request="메모 저장", previous_spec="",
        revision_feedback="", revision_history=[], rubric={"items": []})
    assert not any(item["content"].startswith("최신 검증 의견:") for item in initial)


def test_review_retry_guidance_distinguishes_safe_failed_checks():
    from backend.infrastructure.stage_retry import retry_messages
    from backend.services.rubric import invalid

    def payload(error):
        message = retry_messages([], stage="checklist_critic", attempt=1, error=error)[-1]
        return json.loads(message["content"].split("\n", 1)[1])

    evidence = payload(invalid("rubric_evidence", stage="checklist_critic"))
    score = payload(invalid("rubric_score", stage="checklist_critic"))
    assert evidence["failed_checks"] == ["rubric_evidence"]
    assert score["failed_checks"] == ["rubric_score"]
    assert evidence["validation_failures"] and score["validation_failures"]
    assert evidence["validation_failures"] != score["validation_failures"]
    guidance = " ".join(score["validation_failures"])
    assert all(field in guidance for field in ("score_reason", "revision_directives"))
    assert "서버" in guidance


def test_review_retry_does_not_forward_untrusted_failed_check_or_details():
    from backend.errors import ReviewValidationError
    from backend.infrastructure.stage_retry import retry_messages

    error = ReviewValidationError(["PRIVATE_MODEL_RESPONSE"], check="rubric_evidence")
    error.failed_checks = ["rubric_evidence", "PRIVATE_MODEL_CHECK"]
    result = retry_messages([], stage="checklist_critic", attempt=1, error=error)
    payload = json.loads(result[-1]["content"].split("\n", 1)[1])
    assert payload["failed_checks"] == ["rubric_evidence"]
    assert "PRIVATE_MODEL_CHECK" not in str(payload)
    assert "PRIVATE_MODEL_RESPONSE" not in str(payload)


def test_all_review_checks_have_specific_safe_correction_guidance():
    from backend.errors import ReviewValidationError
    from backend.infrastructure.stage_retry import retry_messages

    guidance = {}
    for check in ReviewValidationError.checks:
        error = ReviewValidationError(["PRIVATE_MODEL_RESPONSE"], check=check)
        payload = json.loads(retry_messages([], stage="review_resolution", attempt=1, error=error)
                             [-1]["content"].split("\n", 1)[1])
        assert payload["failed_checks"] == [check]
        assert len(payload["validation_failures"]) == 1
        assert "PRIVATE_MODEL_RESPONSE" not in str(payload)
        guidance[check] = payload["validation_failures"][0]
    unknown = ReviewValidationError()
    unknown.failed_checks = ["PRIVATE_MODEL_CHECK"]
    fallback = json.loads(retry_messages([], stage="review_resolution", attempt=1, error=unknown)
                          [-1]["content"].split("\n", 1)[1])["validation_failures"][0]
    assert all(value != fallback for value in guidance.values())
    assert "한국어" in guidance["resolution_language"]
    assert "basis" in guidance["resolution_basis"].lower()
