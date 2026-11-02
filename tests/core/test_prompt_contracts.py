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
        mandatory_requirements=[RequirementItem("REQ-001", "Store notes locally.", original_text="메모 저장")])
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


def instruction_sizes():
    return {stage: len(text) for stage, text in assembled_instructions().items()}


# 동일한 고정 입력과 실제 메시지/제공자 조합 경로에서 측정한 리팩터링 전 글자 수.
BASELINE_SIZES = {"checklist_critic": 8492, "interview": 4223, "requirement_lock": 5429,
                  "review_resolution": 7289, "rubric_generate": 2672, "spec_compile": 10067}


def test_composed_instruction_size_reduction_includes_shared_fragments():
    sizes = instruction_sizes()
    large = ("spec_compile", "checklist_critic", "review_resolution")
    assert sum(sizes[stage] for stage in large) <= sum(BASELINE_SIZES[stage] for stage in large) * .75
    assert all(sizes[stage] < BASELINE_SIZES[stage] for stage in sizes)


@pytest.mark.parametrize("stage", BASELINE_SIZES)
def test_question_and_language_contracts_are_composed_once_for_relevant_stages(stage):
    from backend.infrastructure.output_language import LANGUAGE_RULES
    from backend.infrastructure.prompts import PROMPT_DIR

    text = assembled_instructions()[stage]
    question = (PROMPT_DIR / "_question_contract.md").read_text(encoding="utf-8").strip()
    expected = int(stage in {"interview", "checklist_critic", "review_resolution"})
    assert text.count(question) == expected
    assert text.count(LANGUAGE_RULES[stage]) == 1
    assert not re.search(r"[가-힣]", text)
    assert all(text.count(heading) == 1 for heading in ("## Role", "## Judgment", "## Output", "## Exceptions"))


def test_shared_question_advice_does_not_become_confirmation():
    for stage in ("interview", "checklist_critic", "review_resolution"):
        text = assembled_instructions()[stage]
        assert all(term in text for term in ("single_choice", "multiple_choice", "options=[]", "Other",
            "impact", "assumptions", "recommendation", "otherwise null", "display-only advice",
            "not a selection", "never reuse them as confirmed decisions"))
    text = assembled_instructions()["review_resolution"]
    assert "decision_form=null" in text
    assert "question and its decision_form" in text


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
                            if item["content"].startswith("Stage retry context:\n")))
    assert retry["max_retries"] == MAX_RETRIES == 3
    assert retry["validation_failures"] == ["problem: ko"]


def test_source_contract_keeps_selected_history_conditions_and_actor_without_duplicate_advice():
    from backend.infrastructure.prompt_context import REFERENCE_RULES
    for stage, text in assembled_instructions().items():
        if stage == "rubric_generate":
            assert REFERENCE_RULES not in text  # 이 단계는 S/K가 아닌 제품 근거를 직접 사용한다.
            continue
        assert text.count(REFERENCE_RULES) == 1
        assert all(term in text for term in ("original_actor", "conditions", "actor=llm", "user-authored quotation",
            "explicitly selected project decisions", "rationale or other history", "interview/review resolution"))
        assert "Historical search results are reference material" not in text


def test_compiler_retains_block_trace_and_implementation_order_contracts():
    text = assembled_instructions()["spec_compile"]
    assert all(term in text for term in ("out_of_scope, which must be []", "LOCKED-", "spec_links",
        "one self-contained Markdown bullet per block", "General explanation, code and original quotations",
        "globally unique stable item_id", "Assumption:", "basis_refs", "actor=llm", "acceptance_criteria_seed",
        "spec_item_ids", "completion_item_ids", "depends_on", "without cycles", "non-required work",
        "do not claim execution", "workflow_constraints", "rubric IDs and verdicts"))


def test_critic_has_one_consistent_absence_contract_and_keeps_general_review():
    text = assembled_instructions()["checklist_critic"]
    assert all(term in text for term in ("general defect review", "a rubric does not replace", "sole empty-quote exception",
        "linked rubric absence", "evidence_kind=absence", 'quote=""', "absence cannot PASS", "exactly one blocking/major",
        "rubric_ids", "same defect", "draft reflects it", "workflow constraints".capitalize(), "non_scope"))
    assert "Every issue, including structural issues, must include" not in text


def test_requirement_and_resolution_keep_confirmation_and_requestion_boundaries():
    texts = assembled_instructions()
    assert all(term in texts["requirement_lock"] for term in ("actor=user requires an exact quote", "actor=llm",
        "rationale", "when absent", "unresolved_questions=[]", "mandatory IDs", "shared source", "WF-*",
        "pre_answer alone", "never approve a high-risk assumption", "not confirmed choices"))
    assert all(term in texts["review_resolution"] for term in ("confirmed_basis", "allowed_resolution_refs.basis_refs",
        "NEW current user feedback", "existing answered decision", "conflicting_source=null", "diagnose_keys",
        "final_assessment=true", "ask_user", "not another repair", "grants no extra retries",
        "rubric/model failures", "missing_information=\"\""))


def test_interview_and_rubric_keep_material_choice_and_scope_boundaries():
    texts = assembled_instructions()
    assert all(term in texts["interview"] for term in ("materially affecting", "normalized question text",
        "ask_user", "stop_reason", "confirmed answers", "inferred pre_answers", "not product decisions"))
    assert all(term in texts["rubric_generate"] for term in ("every mandatory requirement", "product constraint",
        "optional/recommended", "non_scope", "own requirement ID", "supplementary evidence",
        "Do not add obligations", "unspecified material decisions", "WF-*"))


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
