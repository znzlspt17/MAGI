"""사용자 작업 지시의 출처와 제품 명세 경계를 검증한다."""

import json
from unittest.mock import Mock

import httpx2
import pytest
from pydantic import ValidationError

from backend.errors import InvalidStateError, RequirementNormalizationError
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.conversation_state import POLICY
from backend.infrastructure.prompt_messages import messages
from backend.infrastructure.provider_call import complete_with_usage
from backend.knowledge.projection import project
from backend.knowledge.runtime import RunKnowledge
from backend.knowledge.trace import validate_decisions, validate_links
from backend.models import InterviewResult, LockResponse, QAItem, RequirementLockSheet, SpecDraftResponse
from backend.providers.llm_provider import OpenAIProvider
from backend.services.checklist_critic import ChecklistCritic
from backend.services.requirement_lock_builder import RequirementLockBuilder
from backend.services.workflow_constraints import validate_product_boundary
from test_conversation_structured import packet, transport
from test_output_language import lock_value
from test_review_decisions import DecisionProvider, engine_for, read_state
from prompt_fixtures import short_sources, model_context


WORKFLOW = "구현 에이전트 실행 금지"
MIXED = WORKFLOW + ", 멀티플레이 제외"


def workflow(source="user_request", original=WORKFLOW):
    return dict(id="WF-001", text="Do not run implementation agents.",
                source=source, sources=[source], original_text=original)


def value(source="user_request"):
    result = lock_value()
    result["mandatory_requirements"][0].update(source="user_request", sources=[])
    result["workflow_constraints"] = [workflow(source)]
    result["non_scope"] = [dict(id="NS-001", text="Multiplayer is excluded.",
        source=source, sources=[source], original_text="멀티플레이 제외")]
    return result


def build(result, state=None, answers=()):
    provider = Mock(return_value=json.dumps(result, ensure_ascii=False))
    sheet = RequirementLockBuilder().build(state or {"user_request": MIXED}, {},
        InterviewResult("feature", [], [], pre_answers=list(answers)), provider_messages_fn=provider)
    return sheet, provider


def test_empty_answer_draft_and_required_current_contract():
    sheet = RequirementLockSheet.build_fallback()
    assert not sheet.mandatory_requirements and not sheet.non_scope and not sheet.workflow_constraints
    assert not sheet.acceptance_criteria_seed and "REQ-001" not in sheet.to_markdown()
    old = value()
    del old["workflow_constraints"]
    with pytest.raises(InvalidStateError, match="Start a new generation"):
        RequirementLockSheet.from_dict(old)
    with pytest.raises(ValidationError):
        LockResponse.model_validate(old)
    callback = Mock()
    with pytest.raises(InvalidStateError):
        ChecklistCritic().critique("draft", sheet, provider_messages_fn=callback)
    callback.assert_not_called()
    from backend.services.spec_compiler import SpecCompiler
    with pytest.raises(InvalidStateError):
        object.__new__(SpecCompiler).compile(sheet, None)


@pytest.mark.parametrize("source", ["user_request", "user_answer:Q-1", "user_feedback"])
def test_product_exclusion_and_workflow_preserve_mixed_user_source(source):
    state = {"user_request": MIXED if source == "user_request" else "메모 앱"}
    answers = []
    if source.startswith("user_answer"):
        state["confirmed_user_sources"] = {source: MIXED}
        answers = [QAItem("Q-1", "제약은?", MIXED)]
    if source == "user_feedback":
        state["revision_feedback"] = MIXED
    sheet, provider = build(value(source), state, answers)
    assert provider.call_count == 1
    assert sheet.workflow_constraints[0].original_text == WORKFLOW
    assert sheet.workflow_constraints[0].source == sheet.non_scope[0].source == source
    assert "작업 방식에 대한 요청" in sheet.to_markdown()
    assert RequirementLockSheet.from_dict(sheet.to_dict()).to_dict() == sheet.to_dict()
    nodes, _ = project("job", {**state, "requirement_lock_sheet": sheet.to_dict()}, {})
    assert all(node["attrs"].get("scope") == "product" for node in nodes if node["kind"] in {"requirement", "decision", "spec"})
    assert not any(node["kind"] != "input" and WORKFLOW in node["body"] for node in nodes)


@pytest.mark.parametrize("change", ["invented_quote", "document_source", "inferred_answer", "product_id", "criterion", "decision"])
def test_fabricated_sources_and_cross_category_references_are_rejected(change):
    result = value()
    state = {"user_request": MIXED}
    answers = []
    if change == "invented_quote": result["workflow_constraints"][0]["original_text"] = "존재하지 않는 원문"
    if change == "document_source": result["workflow_constraints"][0].update(source="document:README", sources=[])
    if change == "inferred_answer":
        state = {"user_request": "메모 앱"}
        result["workflow_constraints"] = [workflow("user_answer:Q-1")]
        answers = [QAItem("Q-1", "작업 방법?", MIXED)]
    if change == "product_id": result["mandatory_requirements"][0]["id"] = "WF-001"
    if change == "criterion": result["acceptance_criteria_seed"] = ["WF-001 must be satisfied."]
    if change == "decision": result["decisions"] = [dict(id="DEC-001", text=WORKFLOW, actor="user", rationale="", conditions="", sources=["user_request"], requirement_ids=[], reused_node_ids=[])]
    with pytest.raises(RequirementNormalizationError):
        build(result, state, answers)


def test_workflow_cannot_be_product_link_or_generated_prose():
    sheet, _ = build(value())
    with pytest.raises(ValueError):
        validate_links([dict(item_id="I", section="architecture", quote="Keep notes.",
            requirement_ids=["WF-001"], decision_ids=[])], [], sheet.to_dict(), {"architecture": "Keep notes."})
    with pytest.raises(ValueError):
        validate_decisions([dict(id="D", text="Choice", actor="llm", rationale="", conditions="", sources=[],
            requirement_ids=["WF-001"], reused_node_ids=[])], sheet.to_dict())
    with pytest.raises(ValueError):
        validate_product_boundary(sheet, [sheet.workflow_constraints[0].text])


def test_sdk_serializes_workflow_as_user_context_and_requires_field(tmp_path):
    sheet, _ = build(value())
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx2.Response(200, json=packet(short_sources(value(), model_context(captured[-1]['input']))))
    product_sheet = sheet.to_dict()
    constraints = product_sheet.pop("workflow_constraints")
    payload = messages("Normalize requirements.", MIXED, json.dumps({"lock_sheet": product_sheet}), workflow_constraints=constraints)
    with transport(handle):
        complete_with_usage(ArtifactWriter(tmp_path), OpenAIProvider(api_key="fake-test-value"), payload,
                            model="gpt-6-luna", stage="requirement_lock")
    sent = captured[0]
    inputs = [{**item, "content": item["content"] if isinstance(item["content"], str) else "".join(block["text"] for block in item["content"])} for item in sent["input"]]
    assert POLICY in inputs[0]["content"]
    assert sent["input"][0]["role"] == "developer"
    assert WORKFLOW not in sent["instructions"]
    workflow_message = next(item for item in inputs if item["content"].startswith("User workflow constraints"))
    assert workflow_message["role"] == "user"
    canonical = next(item["content"] for item in inputs if item["content"].startswith("Canonical context"))
    assert '"workflow_constraints"' not in canonical
    assert "workflow_constraints" in sent["text"]["format"]["schema"]["required"]


def test_generate_answer_compile_review_revise_and_old_resume_block(tmp_path):
    from backend.models import InterviewResponse, ReviewResponse, CompletionResult
    class Provider(DecisionProvider):
        def __init__(self):
            super().__init__([[], [], []])
            self.interviews = 0
            self.compiles = 0
        def complete_result(self, messages, **kwargs):
            schema = kwargs["text_format"]
            if schema is InterviewResponse:
                self.calls.append(schema)
                self.interviews += 1
                questions = [dict(question_id="PRODUCT-003", question="추가 제약은 무엇인가요?")] if self.interviews == 1 else []
                return CompletionResult(text="", parsed=schema(request_type="feature", assumptions=[],
                    blocking_questions=questions, additional_questions=[], pre_answers=[]), response_id="resp_interview")
            result = super().complete_result(messages, **kwargs)
            if schema is LockResponse:
                source_id = self.contexts[schema]["saved_answers"][0]["question_id"]
                result = CompletionResult(text="", parsed=LockResponse.model_validate(short_sources(value("user_answer:" + source_id), self.contexts[schema])), response_id=result.response_id)
                # 수정 의견이 작업 지시만 담아도 제품 요구사항으로 합성하지 않는다.
                if self.interviews > 2:
                    second = short_sources(workflow("user_feedback", "짧게 검토해줘"), self.contexts[schema])
                    second.update(id="WF-002", text="Keep the review concise.")
                    result.parsed.workflow_constraints.append(type(result.parsed.workflow_constraints[0]).model_validate(second))
            if schema is SpecDraftResponse:
                self.compiles += 1
                if self.compiles == 1:
                    result.parsed.mission[0].text = "Do not run implementation agents."
            return result
    provider = Provider()
    engine = engine_for(provider)
    assert engine.generate_from_text(text="메모 앱", output_dir=str(tmp_path)).status == "NEEDS_USER_INPUT"
    question_id = read_state(tmp_path)["blocking_questions"][0].split("]", 1)[0][1:]
    result = engine.answer(str(tmp_path), answers=[dict(question_id=question_id, answer=MIXED)])
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    saved_workflow = read_state(tmp_path)['requirement_lock_sheet']['workflow_constraints'][0]
    assert saved_workflow['source'] == 'user_answer:' + question_id
    assert saved_workflow['original_text'] == WORKFLOW
    feedback = tmp_path / "feedback.txt"
    feedback.write_text("짧게 검토해줘", encoding="utf-8")
    result = engine.revise(output_dir=str(tmp_path), feedback_path=str(feedback))
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    spec = (tmp_path / "draft/approval_candidate_spec.en.md").read_text(encoding="utf-8")
    assert "Multiplayer is excluded." in spec
    assert all(text not in spec for text in ("WF-", WORKFLOW, "Do not run implementation agents.", "MAGI does not implement"))
    assert len(read_state(tmp_path)["requirement_lock_sheet"]["workflow_constraints"]) == 2
    assert provider.compiles == 3  # 최초 작성 보정 1회와 수정 작성 1회
    diagnostic = json.loads((tmp_path / "analysis/spec_compile_validation.json").read_text(encoding="utf-8"))
    assert "workflow" in diagnostic["validation_details"][0]
    old = read_state(tmp_path)
    del old["requirement_lock_sheet"]["workflow_constraints"]
    path = tmp_path / "state/magi_state.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    unchanged = path.read_bytes()
    count = len(provider.calls)
    for action in (lambda: engine.answer(str(tmp_path), answers=[dict(question_id=question_id, answer=MIXED)]),
                   lambda: engine.revise(output_dir=str(tmp_path), feedback_path=str(feedback)),
                   lambda: engine.approve(str(tmp_path))):
        with pytest.raises(InvalidStateError, match="Start a new generation"):
            action()
    assert len(provider.calls) == count and path.read_bytes() == unchanged


def test_unscoped_nodes_are_not_reusable():
    runtime = object.__new__(RunKnowledge)
    runtime.retrieved = {"nodes": [dict(id="old", active=True, kind="requirement", attrs={}),
        dict(id="product", active=True, kind="requirement", attrs={"scope": "product"}),
        dict(id="workflow", active=True, kind="decision", attrs={"scope": "workflow"})]}
    assert runtime.reusable_ids() == {"product"}


def test_document_workflow_fields_remain_untrusted_data():
    payload = messages("Analyze supplied data.", "메모 앱", json.dumps({
        "project_manifest": {"workflow_constraints": [workflow()]}}))
    assert not any(item["content"].startswith("User workflow constraints") for item in payload)
    canonical = next(item for item in payload if item["content"].startswith("Canonical context"))
    assert '"workflow_constraints"' in canonical["content"]
