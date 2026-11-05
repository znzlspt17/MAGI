"""MAGI의 데이터 클래스와 구조화 응답 계약."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

from langgraph.managed import RemainingSteps
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from backend.knowledge.trace import DecisionTrace, SpecLink


STATUS_ANALYZING = "ANALYZING"
STATUS_APPROVED = "APPROVED"
STATUS_COMPILING = "COMPILING"
STATUS_CRITICAL_BLOCKED = "CRITICAL_BLOCKED"
STATUS_CRITIQUING = "CRITIQUING"
STATUS_DRAFT = "DRAFT"
STATUS_FINALIZED = "FINALIZED"
STATUS_NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
STATUS_PASS_PENDING_USER_APPROVAL = "PASS_PENDING_USER_APPROVAL"
STATUS_REJECTED_BY_USER = "REJECTED_BY_USER"
STATUS_RESEARCHING = "RESEARCHING"
VALID_ISSUE_STATUS = {"open", "resolved", "deferred"}
VALID_REQUEST_TYPES = {"product", "feature", "bugfix", "refactor", "infra"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_SEVERITY = {"blocking", "major", "minor"}
_SEVERITY_RANK = {"minor": 0, "major": 1, "blocking": 2}


# 상속에 필요한 기반 클래스를 먼저 정의한다.


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuestionOption(ResponseModel):
    id: str
    label: str
    impact: str | None = Field(default=None, min_length=1, max_length=240, description="관련 이점과 부담을 포함한 조건부 한국어 영향 설명입니다. 참고 정보이며 사용자 결정이 아닙니다.")
    assumptions: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=3, description="영향이 적용되는 한국어 조건이며 확정 요구사항이 아닙니다.")


class QuestionRecommendation(ResponseModel):
    option_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=300, description="제공된 문맥에 근거한 한국어 추천 이유이며 사용자 승인이 아닙니다.")
    assumptions: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=3)


class QuestionFormSpec(ResponseModel):
    input_type: Literal["text", "single_choice", "multiple_choice"] = "text"
    options: list[QuestionOption] = Field(default_factory=list)
    recommendation: QuestionRecommendation | None = Field(default=None, description="선택적 권고입니다. 우선순위나 문맥이 부족하면 null을 사용하고 답변을 미리 선택하지 마세요.")

    @model_validator(mode="after")
    def validate_options(self):
        if self.input_type == "text":
            if self.options:
                raise ValueError("Text questions cannot have options.")
        elif len(self.options) < 2:
            raise ValueError("Choice questions require at least two options.")
        ids = [o.id for o in self.options]
        labels = [o.label.strip() for o in self.options]
        if any(not value.strip() for value in ids + labels) or len(set(ids)) != len(ids) or len(set(labels)) != len(labels):
            raise ValueError("Options require unique non-empty IDs and labels.")
        if self.recommendation is not None:
            recommended = self.recommendation.option_ids
            if (self.input_type == "text" or len(set(recommended)) != len(recommended)
                    or not set(recommended) <= set(ids)
                    or self.input_type == "single_choice" and len(recommended) != 1):
                raise ValueError("Recommendation must reference valid unique options of the question.")
        return self


class QuestionResponse(QuestionFormSpec):
    question_id: str
    question: str = Field(description='한국어 질문입니다. 기존에 인용된 사용자 질문은 그대로 보존하세요.')


# 데이터 클래스와 응답 모델은 클래스 이름의 알파벳순으로 정렬한다.


class AnswerResponse(ResponseModel):
    question_id: str
    question: str
    answer: str


@dataclass(slots=True)
class AssumptionItem:
    id: str
    text: str
    risk: str = "low"

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "text": self.text, "risk": self.risk}

    @classmethod
    def from_dict(cls, data: Any) -> "AssumptionItem":
        if not isinstance(data, dict):
            return cls(id="ASM-UNK", text=str(data or ""), risk="low")
        raw_risk = str(data.get("risk", "low")).lower()
        return cls(
            id=str(data.get("id", "ASM-UNK")),
            text=str(data.get("text", "")),
            risk=raw_risk if raw_risk in VALID_RISK_LEVELS else "low",
        )


class AssumptionResponse(ResponseModel):
    id: str
    text: str = Field(description='정규화된 한국어 가정. risk enum은 변경하지 마세요.')
    risk: Literal["low", "medium", "high"]


@dataclass(slots=True)
class ChecklistItem:
    checklist_id: str
    section: str
    severity: str
    description: str


@dataclass(slots=True, frozen=True)
class CompletionResult:
    text: str
    parsed: BaseModel | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    response_id: str | None = None
    cache_diagnostics: dict[str, Any] | None = None
    cache_write_tokens: int | None = None
    cache_write_30m_tokens: int | None = None
    cache_write_12h_tokens: int | None = None


@dataclass(slots=True)
class EvidenceItem:
    evidence_id: str
    evidence_type: str
    summary: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "summary": self.summary,
            "source": self.source,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class EvidenceResponse(ResponseModel):
    source: str
    quote: str = Field(description='번역하지 않은 원어 그대로의 정확한 근거 인용입니다.')


class InterviewResponse(ResponseModel):
    request_type: Literal["product", "feature", "bugfix", "refactor", "infra"]
    assumptions: list[str] = Field(description='확정되지 않은 가정에 대한 한국어 설명입니다.')
    blocking_questions: list[QuestionResponse] = Field(description='사용자 결정이 필요한 한국어 질문입니다.')
    additional_questions: list[QuestionResponse] = Field(description='한국어 추가 질문입니다.')
    pre_answers: list[AnswerResponse] = Field(description='번역 없이 원문 그대로 보존한 사용자 답변입니다.')


@dataclass(slots=True)
class InterviewResult:
    request_type: str
    blocking_questions: list[str]
    assumptions: list[str]
    pre_answers: list[QAItem] = field(default_factory=list)
    direction_changing_pending: bool = False
    question_forms: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IssueEvidence:
    source: str
    quote: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "quote": self.quote}

    @classmethod
    def from_dict(cls, data: Any) -> "IssueEvidence":
        if not isinstance(data, dict):
            return cls(source="unknown", quote="")
        return cls(
            source=str(data.get("source", "unknown")),
            quote=str(data.get("quote", "")),
        )


@dataclass(slots=True)
class IssuePacket:
    issue_id: str
    section: str
    severity: str  # blocking|major|minor
    blocking: bool
    checklist_id: str
    problem: str
    required_change: str
    requirement_id: str | None = None
    evidence: list[IssueEvidence] = field(default_factory=list)
    suggested_patch: str | None = None
    status: str = "open"  # open|resolved|deferred
    resolution_kind: Literal["auto_fix", "user_decision"] = "auto_fix"
    decision_form: dict[str, Any] | None = None
    decision_question: str | None = None
    decision_answer_id: str | None = None
    defect_kind: str = "spec_omission"
    resolution_reason: str = "확정 요구사항에 따른 명세 보완이 필요합니다."
    missing_information: str = ""
    decision_key: str = ""
    basis_refs: list[str] = field(default_factory=list)
    rubric_ids: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.decision_key:
            self.decision_key = self.checklist_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "section": self.section,
            "severity": self.severity,
            "blocking": self.blocking,
            "checklist_id": self.checklist_id,
            "problem": self.problem,
            "required_change": self.required_change,
            "requirement_id": self.requirement_id,
            "evidence": [e.to_dict() for e in self.evidence],
            "suggested_patch": self.suggested_patch,
            "status": self.status,
            "resolution_kind": self.resolution_kind,
            "decision_form": self.decision_form,
            "decision_question": self.decision_question,
            "decision_answer_id": self.decision_answer_id,
            "defect_kind": self.defect_kind,
            "resolution_reason": self.resolution_reason,
            "missing_information": self.missing_information,
            "decision_key": self.decision_key,
            "basis_refs": list(self.basis_refs),
            "rubric_ids": list(self.rubric_ids),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, fallback_id: str = "ISSUE-UNK"
    ) -> "IssuePacket":
        from backend.errors import InvalidStateError
        if not all(key in data for key in ("defect_kind", "resolution_reason", "missing_information", "decision_key")):
            raise InvalidStateError("Review contract is invalid. Start a new generation.")
        if (data["defect_kind"] not in {"requirements_gap", "spec_omission", "verification_gap", "confirmed_conflict"}
                or not isinstance(data["resolution_reason"], str) or not data["resolution_reason"].strip()
                or not isinstance(data["missing_information"], str) or not isinstance(data["decision_key"], str)
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,100}", data["decision_key"]) is None):
            raise InvalidStateError("Review contract is invalid. Start a new generation.")
        raw_severity = normalize_severity(data.get("severity"), default="major")
        # Enforce: blocking iff severity=="blocking"
        blocking = raw_severity == "blocking"
        raw_status = str(data.get("status", "open")).lower()
        status = raw_status if raw_status in VALID_ISSUE_STATUS else "open"
        evidence_raw = data.get("evidence", [])
        evidence = (
            [IssueEvidence.from_dict(e) for e in evidence_raw]
            if isinstance(evidence_raw, list)
            else []
        )
        return cls(
            issue_id=str(data.get("issue_id", fallback_id)),
            section=str(data.get("section", "unknown")),
            severity=raw_severity,
            blocking=blocking,
            checklist_id=str(data.get("checklist_id", fallback_id)),
            problem=str(data.get("problem", "")),
            required_change=str(data.get("required_change", "")),
            requirement_id=_optional_text(data.get("requirement_id")),
            evidence=evidence,
            suggested_patch=data.get("suggested_patch") or None,
            status=status,
            resolution_kind=data.get("resolution_kind", "auto_fix"),
            decision_form=data.get("decision_form"),
            decision_question=_optional_text(data.get("decision_question")),
            decision_answer_id=_optional_text(data.get("decision_answer_id")),
            defect_kind=data["defect_kind"], resolution_reason=data["resolution_reason"],
            missing_information=data["missing_information"], decision_key=data["decision_key"],
            basis_refs=list(data.get("basis_refs", [])),
            rubric_ids=list(data.get("rubric_ids", [])),
        )


class IssueResponse(ResponseModel):
    rubric_ids: list[str] = Field(default_factory=list)
    decision_form: QuestionFormSpec | None = None
    defect_kind: Literal["requirements_gap", "spec_omission", "verification_gap", "confirmed_conflict"]
    resolution_reason: str = Field(description="확정된 입력에 근거한 한국어 설명입니다.")
    missing_information: str = Field(description="누락된 중요한 선택과 그 영향에 대한 한국어 설명입니다. 누락이 없으면 빈 문자열입니다.")
    decision_key: str = Field(description="문구나 심각도가 바뀌어도 재사용할 안정적인 영문 결정 주제 식별자입니다. 질문 문장을 넣지 마세요.")
    section: str
    severity: Literal["blocking", "major", "minor"]
    checklist_id: str
    problem: str = Field(description='결함에 대한 한국어 설명입니다.')
    required_change: str = Field(description='필요한 수정에 대한 한국어 설명입니다. 제안 명세 문구는 그대로 인용하세요.')
    requirement_id: str | None
    evidence: list[EvidenceResponse]
    resolution_kind: Literal["auto_fix", "user_decision"] = Field(default="auto_fix", description='심각도와 무관합니다. 확정 입력으로 답하지 못한 중요한 선택에만 user_decision을 사용하세요.')
    decision_question: str | None = Field(default=None, description='user_decision에 필요한 한국어 질문이며 그렇지 않으면 null입니다. 동일 결정은 이슈와 검토를 넘어 같은 문구를 사용하세요.')


class LockResponse(ResponseModel):
    decisions: list[DecisionTrace] = Field(default_factory=list, description='안정적인 ID를 가진 명시적 선택입니다. actor=user에는 정확한 사용자 인용과 검증된 출처/요구사항 ID가 필요하며 재사용은 actor=llm을 유지합니다.')
    request_summary: str = Field(description='사용자 요청의 한국어 요약입니다.')
    mandatory_requirements: list[RequirementResponse]
    recommended_requirements: list[RequirementResponse]
    optional_requirements: list[RequirementResponse]
    non_scope: list[RequirementResponse]
    workflow_constraints: list[WorkflowConstraintResponse] = Field(description="대상 제품 요구사항과 분리된 MAGI 작업 방식에 대한 사용자 요청입니다. 필수 배열이며 없으면 비웁니다. WF-* ID와 검증된 정확한 사용자 인용을 사용하세요.")
    assumptions: list[AssumptionResponse]
    constraints: list[RequirementResponse]
    acceptance_criteria_seed: list[str] = Field(description='요구사항 ID를 인용하는 관찰 가능한 한국어 수용 기준입니다.')
    unresolved_questions: list[str] = Field(description='미해결 한국어 질문이며 인터뷰 해결 후에는 비어 있어야 합니다.')


@dataclass(slots=True)
class State:
    run_id: str
    status: str
    user_request: str
    original_user_request: str = ""
    web_search_mode: str = "auto"
    research: dict[str, Any] = field(default_factory=dict)
    # interview stage
    request_type: str = ""
    assumptions: list[str] = field(default_factory=list)
    blocking_questions: list[str] = field(default_factory=list)
    question_forms: dict[str, Any] = field(default_factory=dict)
    awaiting_input_reason: Literal["interview", "review"] | None = None
    review_questions: list[dict[str, Any]] = field(default_factory=list)
    review_history: list[dict[str, Any]] = field(default_factory=list)
    resolution_history: list[dict[str, Any]] = field(default_factory=list)
    diagnosed_keys: list[str] = field(default_factory=list)
    resolution_stop: bool = False
    confirmed_user_sources: dict[str, str] = field(default_factory=dict)
    reused_decisions: list[dict[str, Any]] = field(default_factory=list)
    interview_pre_answers: list[dict[str, Any]] = field(default_factory=list)
    # requirement lock stage
    requirement_lock: str = ""
    requirement_lock_sheet: dict[str, Any] | None = field(default=None)
    rubric: dict[str, Any] = field(default_factory=dict)
    rubric_evaluation: dict[str, Any] = field(default_factory=dict)
    rubric_summary: dict[str, Any] = field(default_factory=dict)
    refinement: dict[str, Any] = field(default_factory=dict)
    approval_acceptance: dict[str, Any] = field(default_factory=dict)
    # critic stage
    structured_issues: list[dict[str, Any]] = field(default_factory=list)
    critic_pass_count: int = 0
    max_critic_passes: int = 5
    # artifact tracking
    approval_candidate_spec: str | None = None
    final_agent_spec: str | None = None
    latest_completed: dict[str, str] | None = None
    critical_report: str | None = None
    user_approval_status: str = "PENDING"
    revision_feedback: str = ""
    revision_history: list[str] = field(default_factory=list)
    created_artifacts: list[str] = field(default_factory=list)
    workflow_schema: int = 1
    revision: int = 0
    plan: dict[str, Any] = field(default_factory=dict)
    plan_history: list[dict[str, Any]] = field(default_factory=list)
    task_results: list[dict[str, Any]] = field(default_factory=list)
    task_messages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    knowledge_context: dict[str, Any] = field(default_factory=dict)
    completed_tasks: list[str] = field(default_factory=list)
    execution_segment: int = 0
    execution_diagnostic: dict[str, Any] = field(default_factory=dict)
    execution_constraints: dict[str, Any] = field(default_factory=dict)
    wait_reason: str = ""
    stop_reason: str = ""
    final_resolution_keys: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    candidate_hash: str = ""
    document_versions: list[dict[str, Any]] = field(default_factory=list)
    pending_input: dict[str, Any] = field(default_factory=dict)
    mcp: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_workflow_state(self) -> WorkflowState:
        return self.to_dict()  # type: ignore[return-value]

    @classmethod
    def from_workflow_state(cls, data: WorkflowState) -> "State":
        return cls.from_dict(dict(data))


@dataclass(slots=True)
class ModelRoute:
    provider: str
    model: str

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}


@dataclass(slots=True)
class QAItem:
    question_id: str
    question: str
    answer: str
    selection: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **({"selection": self.selection} if self.selection is not None else {}),
            "question_id": self.question_id,
            "question": self.question,
            "answer": self.answer,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "QAItem":
        if not isinstance(data, dict):
            return cls(question_id="Q-UNK", question="", answer="")
        return cls(
            question_id=str(data.get("question_id", "Q-UNK")),
            question=str(data.get("question", "")),
            answer=str(data.get("answer", "")),
            selection=data.get("selection"),
        )


@dataclass(slots=True)
class Question:
    question_id: str
    text: str
    direction_changing: bool
    applies_to: tuple[str, ...]


@dataclass(slots=True)
class RequirementItem:
    id: str
    text: str
    source: str = "user_request"
    original_text: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "original_text": self.original_text,
            "sources": list(self.sources),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "RequirementItem":
        if not isinstance(data, dict):
            return cls(id="REQ-UNK", text=str(data or ""), source="user_request")
        raw_sources = data.get("sources", [])
        return cls(
            id=str(data.get("id", "REQ-UNK")),
            text=str(data.get("text", "")),
            source=str(data.get("source", "user_request")),
            original_text=str(data.get("original_text", "")),
            sources=[
                item.strip()
                for item in raw_sources
                if isinstance(item, str) and item.strip()
            ]
            if isinstance(raw_sources, list)
            else [],
        )


@dataclass(slots=True)
class RequirementLockSheet:
    lock_id: str
    request_type: str  # product|feature|bugfix|refactor|infra
    request_summary: str
    workflow_constraints: list[RequirementItem]
    user_answers: list[QAItem] = field(default_factory=list)
    mandatory_requirements: list[RequirementItem] = field(default_factory=list)
    recommended_requirements: list[RequirementItem] = field(default_factory=list)
    optional_requirements: list[RequirementItem] = field(default_factory=list)
    non_scope: list[RequirementItem] = field(default_factory=list)
    assumptions: list[AssumptionItem] = field(default_factory=list)
    constraints: list[RequirementItem] = field(default_factory=list)
    acceptance_criteria_seed: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lock_id": self.lock_id,
            "request_type": self.request_type,
            "request_summary": self.request_summary,
            "user_answers": [a.to_dict() for a in self.user_answers],
            "mandatory_requirements": [
                r.to_dict() for r in self.mandatory_requirements
            ],
            "recommended_requirements": [
                r.to_dict() for r in self.recommended_requirements
            ],
            "optional_requirements": [r.to_dict() for r in self.optional_requirements],
            "non_scope": [r.to_dict() for r in self.non_scope],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "constraints": [r.to_dict() for r in self.constraints],
            "workflow_constraints": [r.to_dict() for r in self.workflow_constraints],
            "acceptance_criteria_seed": list(self.acceptance_criteria_seed),
            "unresolved_questions": list(self.unresolved_questions),
            "source_refs": list(self.source_refs),
            "decisions": list(self.decisions),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RequirementLockSheet":
        from backend.errors import InvalidStateError
        if not isinstance(data, dict) or not isinstance(data.get("workflow_constraints"), list):
            raise InvalidStateError("Requirement lock contract is invalid. Start a new generation.")
        try:
            workflow = [WorkflowConstraintResponse.model_validate(item).model_dump() for item in data["workflow_constraints"]]
        except (ValueError, TypeError):
            raise InvalidStateError("Requirement lock contract is invalid. Start a new generation.") from None
        def _req_list(key: str) -> list[RequirementItem]:
            return [RequirementItem.from_dict(i) for i in data.get(key, []) if i]

        def _asm_list(key: str) -> list[AssumptionItem]:
            return [AssumptionItem.from_dict(i) for i in data.get(key, []) if i]

        def _qa_list(key: str) -> list[QAItem]:
            return [QAItem.from_dict(i) for i in data.get(key, []) if i]

        def _str_list(key: str) -> list[str]:
            return [str(i) for i in data.get(key, []) if str(i).strip()]

        raw_type = str(data.get("request_type", "feature"))
        result = cls(
            lock_id=str(data.get("lock_id", f"lock_{uuid4().hex[:8]}")),
            request_type=raw_type if raw_type in VALID_REQUEST_TYPES else "feature",
            request_summary=str(data.get("request_summary", "")),
            user_answers=_qa_list("user_answers"),
            mandatory_requirements=_req_list("mandatory_requirements"),
            recommended_requirements=_req_list("recommended_requirements"),
            optional_requirements=_req_list("optional_requirements"),
            non_scope=_req_list("non_scope"),
            assumptions=_asm_list("assumptions"),
            constraints=_req_list("constraints"),
            workflow_constraints=[RequirementItem.from_dict(item) for item in workflow],
            acceptance_criteria_seed=_str_list("acceptance_criteria_seed"),
            unresolved_questions=_str_list("unresolved_questions"),
            source_refs=_str_list("source_refs"),
            decisions=list(data.get("decisions", [])),
        )
        from backend.services.workflow_constraints import validate_workflow
        try:
            validate_workflow(result.workflow_constraints)
        except ValueError:
            raise InvalidStateError("Requirement lock contract is invalid. Start a new generation.") from None
        return result

    def require_validated(self):
        """작성·검토·승인에는 확정된 제품 요구사항이 필요하다."""
        from backend.errors import InvalidStateError
        if not self.mandatory_requirements or self.unresolved_questions:
            raise InvalidStateError("Validated requirement lock is required. Start a new generation.")
        for group in (self.mandatory_requirements, self.recommended_requirements, self.optional_requirements, self.constraints, self.non_scope):
            if any(not item.id.strip() or not item.text.strip() or item.id.startswith("WF-") or not item.source.strip() or "system" in [item.source, *item.sources] for item in group):
                raise InvalidStateError("Requirement lock contract is invalid. Start a new generation.")
        from backend.services.workflow_constraints import validate_workflow, validate_product_boundary
        try:
            validate_workflow(self.workflow_constraints)
            validate_product_boundary(self)
        except ValueError:
            raise InvalidStateError("Requirement lock contract is invalid. Start a new generation.") from None
        return self

    def to_markdown(self) -> str:
        """Generate Korean Markdown summary for analysis/requirement_lock_sheet.ko.md."""
        lines = [
            "# 요구사항 잠금 시트",
            "",
            f"- **잠금 ID**: {self.lock_id}",
            f"- **요청 유형**: {self.request_type}",
            f"- **요청 요약**: {self.request_summary}",
            "",
        ]
        if self.user_answers:
            lines += ["## 사용자 답변", ""]
            for qa in self.user_answers:
                lines += [f"**{qa.question}**", f"> {qa.answer}", ""]

        if self.mandatory_requirements:
            lines += ["## 필수 요구사항 (Mandatory)", ""]
            for r in self.mandatory_requirements:
                lines.append(f"- [{r.id}] {r.text}")
            lines.append("")

        if self.non_scope:
            lines += ["## 비범위 (Out of Scope)", ""]
            for r in self.non_scope:
                lines.append(f"- [{r.id}] {r.text}")
            lines.append("")

        if self.workflow_constraints:
            lines += ["## 작업 방식에 대한 요청 — 제품 명세에서 제외", ""]
            for item in self.workflow_constraints:
                lines += [f"- [{item.id}] {item.original_text}", f"  - 출처: {item.source}"]
            lines.append("")

        if self.assumptions:
            lines += ["## 가정 (Assumptions)", ""]
            for a in self.assumptions:
                lines.append(f"- [{a.id}][{a.risk}] {a.text}")
            lines.append("")

        if self.acceptance_criteria_seed:
            lines += ["## 완료 기준 씨앗 (Acceptance Criteria Seed)", ""]
            for s in self.acceptance_criteria_seed:
                lines.append(f"- {s}")
            lines.append("")

        if self.unresolved_questions:
            lines += ["## 미해결 질문", ""]
            for q in self.unresolved_questions:
                lines.append(f"- {q}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def build_fallback(
        cls,
        *,
        request_type: str = "feature",
        request_summary: str = "",
        blocking_questions: list[str] | None = None,
        assumptions: list[str] | None = None,
    ) -> "RequirementLockSheet":
        """답변 수집용 빈 초안. 제품 요구사항이나 내부 작업 규칙을 합성하지 않는다."""
        return cls(
            workflow_constraints=[],
            lock_id=f"lock_{uuid4().hex[:8]}",
            request_type=request_type
            if request_type in VALID_REQUEST_TYPES
            else "feature",
            request_summary=request_summary or "사용자 요청 기반 명세 생성",
            assumptions=[
                AssumptionItem(
                    id="ASM-001",
                    text=a,
                    risk="low",
                )
                for a in (
                    assumptions or []
                )
            ],
            unresolved_questions=list(blocking_questions or []),
            source_refs=["raw/user_request.md"],
        )


class RequirementResponse(ResponseModel):
    id: str
    text: str = Field(description='정규화된 한국어 요구사항입니다.')
    source: str
    original_text: str = Field(description='번역하지 않은 정확한 사용자 원문이며 해당하지 않으면 빈 문자열입니다.')
    sources: list[str]


class WorkflowConstraintResponse(RequirementResponse):
    original_text: str = Field(description="대상 제품 동작이 아닌 MAGI 작업 방식을 설명하는 실제 사용자 입력의 정확하고 비어 있지 않은 인용입니다.")


LockResponse.model_rebuild()


class ResolutionItem(ResponseModel):
    decision_form: QuestionFormSpec | None = None
    issue_id: str
    defect_kind: Literal["requirements_gap", "spec_omission", "verification_gap", "confirmed_conflict"]
    resolution_kind: Literal["auto_fix", "user_decision"]
    resolution_reason: str
    missing_information: str
    decision_key: str
    decision_question: str | None
    required_change: str
    basis_refs: list[str]
    impact: Literal["none", "scope", "behavior", "data", "cost"]
    conflicting_source: str | None = Field(description="새 사용자 요청이 이미 답변된 결정과 충돌할 때만 현재 피드백의 제공된 S 참조를 사용하고 그렇지 않으면 null입니다.")


class ReviewResolutionResponse(ResponseModel):
    resolutions: list[ResolutionItem]


class RubricBasis(ResponseModel):
    reference: str
    quote: str = Field(min_length=1)


class RubricItem(ResponseModel):
    rubric_id: str = Field(pattern=r"^RUB-[A-Za-z0-9_-]{1,80}$")
    requirement_id: str
    importance: Literal["core", "critical", "secondary"]
    category: Literal["requirement", "contract", "data_flow", "failure_completion", "acceptance_test"]
    basis: list[RubricBasis] = Field(min_length=1)
    condition: str = Field(min_length=1, description="확정된 제품 요구사항에만 근거한 한국어 평가 조건입니다. 없는 의무를 만들거나 미결 설계를 선택하지 마세요.")
    sections: list[str] = Field(min_length=1, description="검사할 SpecResponse 섹션 필드 이름입니다.")


class RubricResponse(ResponseModel):
    items: list[RubricItem]


class RubricVerdict(ResponseModel):
    rubric_id: str
    verdict: Literal["PASS", "FAIL", "UNDETERMINED"]
    section: str
    evidence_kind: Literal["quote", "absence"]
    quote: str
    reason: str = Field(min_length=1, description="판정의 한국어 설명입니다. absence인 경우 검사 섹션의 누락 사항을 밝히세요.")
    issue_checklist_id: str | None = Field(description="PASS가 아니면 같은 requirement와 rubric_ids를 가진 정확히 한 이슈의 checklist_id입니다. core/critical은 blocking/major, secondary는 minor도 허용합니다. PASS면 null입니다.")


class ReviewResponse(ResponseModel):
    score: int = Field(ge=1, le=10, strict=True)
    score_reason: str = Field(min_length=1)
    critical_failures: list[str]
    revision_directives: list[str]
    issues: list[IssueResponse]
    rubric_verdicts: list[RubricVerdict] = Field(default_factory=list)


class SpecResponse(ResponseModel):
    decisions: list[DecisionTrace] = Field(default_factory=list, description='추가적인 명시적 LLM 선택입니다. 기존 결정 ID는 다시 선언하지 말고 링크에 보존하세요. 채택한 참조에 적용 이유와 reused_node_ids를 포함하세요.')
    spec_links: list[SpecLink] = Field(default_factory=list, description='생성된 본문 블록으로 애플리케이션이 구성한 정식 링크입니다. 인용은 실제 표시되는 원문입니다.')
    mission: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    background: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    user_intent: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    in_scope: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    out_of_scope: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    definitions: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    evidence_summary: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    recommended_requirements: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    optional_requirements: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    forbidden_behaviors: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    input_contract: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    output_contract: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    architecture: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    module_responsibilities: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    data_flow: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    error_handling_policy: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    configuration_policy: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    persistence_artifact_policy: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    implementation_order: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    acceptance_criteria: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    test_plan: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    manual_verification_checklist: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")
    instructions_for_ai_coding_agent: str = Field(description="한국어 섹션 본문입니다. 코드, 경로 및 표시된 원문 인용은 보존하세요.")

    def markdown(self) -> str:
        """고정 heading과 잠금 섹션은 모델이 생성하지 않는다."""
        from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS

        fields = iter(value for key, value in self.model_dump().items() if key not in {"decisions", "spec_links"})
        sections = []
        for heading in REQUIRED_FINAL_SPEC_HEADINGS:
            if heading in {"# 최종 에이전트 명세", "## 4. 범위", "## 7. 필수 요구사항"}:
                sections.append(heading)
            else:
                sections.append(heading + "\n\n" + next(fields))
        return "\n\n".join(sections) + "\n"


class SpecBlock(ResponseModel):
    """명세 본문과 연결 정보를 한 번만 생성하는 출력 단위."""

    item_id: str = Field(description="모든 섹션에서 유일하고 안정적인 블록 ID입니다. 예약된 LOCKED- 접두사는 사용하지 마세요.")
    text: str = Field(description="표시할 한국어 문단, 목록, 표 또는 코드 블록입니다. 다른 곳에서 인용으로 반복하지 마세요.")
    requirement_ids: list[str] = Field(description="이 블록에서 구체화하는 제공된 잠금 요구사항 ID만 포함하세요.")
    decision_ids: list[str] = Field(description="제공된 잠금 결정 또는 이 응답에서 선언한 추가 결정만 포함하세요.")


class ImplementationTask(SpecBlock):
    title: str = Field(description="짧은 한국어 구현 작업 제목입니다.")
    depends_on: list[str] = Field(description="선행 작업 item ID이며 순환이나 자기 참조는 허용하지 않습니다.")
    spec_item_ids: list[str] = Field(min_length=1, description="implementation_order 및 검증 섹션 밖에 있는 이 응답의 실제 동작 블록 ID입니다.")
    completion_item_ids: list[str] = Field(min_length=1, description="acceptance_criteria, test_plan 또는 manual_verification_checklist에 있는 기존 블록 ID입니다.")


# 저장·조회 형식인 SpecResponse는 유지하고 제공자 출력만 블록 구조로 분리한다.
_draft_fields: dict[str, Any] = {
    "decisions": (list[DecisionTrace], Field(default_factory=list)),
    **{name: (list[ImplementationTask] if name == "implementation_order" else list[SpecBlock], Field(description=(
        "확정된 제품 non_scope로 애플리케이션이 조립하는 섹션입니다. 빈 배열을 반환하고 내용이나 참조를 생성하지 마세요."
        if name == "out_of_scope" else "이 섹션의 순서가 있는 실질적인 한국어 본문 블록입니다. 하나 이상 포함하세요.")))
       for name in SpecResponse.model_fields if name not in {"decisions", "spec_links"}},
}
SpecDraftResponse = create_model("SpecDraftResponse", __base__=ResponseModel, **_draft_fields)


def assemble_spec_draft(draft, sheet, task_plan=None):
    """실제 출력 본문에서만 인용을 만들고 기존 명세·추적 형식으로 변환한다."""
    from backend.errors import SpecCompilationError
    from backend.knowledge.trace import REQUIREMENT_GROUPS
    from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS, _mask_fenced_code
    known_requirements = {item["id"] for group in REQUIREMENT_GROUPS for item in sheet.to_dict().get(group, [])}
    known_decisions = {item["id"] for item in sheet.decisions} | {item.id for item in draft.decisions}
    headings = set(REQUIRED_FINAL_SPEC_HEADINGS) | {"### 확정된 제약"}
    from backend.services.implementation_plan import prepare_plan
    task_plan = task_plan or prepare_plan(draft, sheet)
    sections: dict[str, str] = {}
    links: list[SpecLink] = []
    identities: set[str] = set()
    for name in SpecResponse.model_fields:
        if name in {"decisions", "spec_links"}:
            continue
        if name == "out_of_scope":
            # 앱이 교체하는 모델 블록은 ID·내용 검증이나 구현 근거에 사용하지 않는다.
            sections[name] = "\n".join(f"- [{item.id}] {item.text}" for item in sheet.non_scope) or "명시된 제품 범위 제외가 없습니다."
            links.extend(SpecLink(item_id="LOCKED-" + item.id, section=name, quote=item.text,
                                  requirement_ids=[item.id], decision_ids=[]) for item in sheet.non_scope)
            continue
        blocks = getattr(draft, name)
        if name == "implementation_order":
            blocks = [SpecBlock(item_id=t["item_id"], text=t["rendered"], requirement_ids=t["requirement_ids"], decision_ids=t["decision_ids"]) for t in task_plan["tasks"]]
        if not blocks:
            raise SpecCompilationError([f"{name}: 실질적인 본문 블록을 하나 이상 포함하세요."], check="spec_blocks",
                                       block_reason="empty_section", section=name)
        for index, block in enumerate(blocks):
            if not block.item_id.strip() or block.item_id in identities or block.item_id.startswith("LOCKED-"):
                raise SpecCompilationError([f"{name}[{index}].item_id: LOCKED- 접두사 없이 비어 있지 않은 고유한 안정적 ID를 사용하세요."], check="spec_blocks",
                                           block_reason=("empty_item_id" if not block.item_id.strip() else
                                                         "duplicate_item_id" if block.item_id in identities else "reserved_item_id"),
                                           section=name, index=index, field="item_id")
            identities.add(block.item_id)
            if not block.text.strip():
                raise SpecCompilationError([f"{name}[{index}].text: 실질적인 한국어 내용을 포함하세요."], check="spec_blocks",
                                           block_reason="empty_text", section=name, index=index, field="text")
            if not set(block.requirement_ids) <= known_requirements:
                raise SpecCompilationError([f"{name}[{index}].requirement_ids: 제공된 요구사항 ID만 사용하세요."], check="spec_blocks",
                                           block_reason="unknown_requirement", section=name, index=index, field="requirement_ids")
            if not set(block.decision_ids) <= known_decisions:
                raise SpecCompilationError([f"{name}[{index}].decision_ids: 알려진 결정 ID만 사용하세요."], check="spec_blocks",
                                           block_reason="unknown_decision", section=name, index=index, field="decision_ids")
            if any(line.strip() in headings for line in _mask_fenced_code(block.text).splitlines()):
                raise SpecCompilationError([f"{name}[{index}].text: 고정 섹션 제목과 확정된 제약 제목은 애플리케이션이 작성하므로 제외하세요."], check="spec_blocks",
                                           block_reason="fixed_heading", section=name, index=index, field="text")
        sections[name] = "\n\n".join(block.text.rstrip() for block in blocks)
        links.extend(SpecLink(item_id=block.item_id, section=name, quote=block.text.rstrip(),
                              requirement_ids=block.requirement_ids, decision_ids=block.decision_ids)
                     for block in blocks if block.requirement_ids or block.decision_ids)
    return SpecResponse(decisions=draft.decisions, spec_links=links, **sections)


# LangGraph 경계에서 사용할 정적 계약. State와의 필드 일치는 계약 테스트로 확인한다.
class WorkflowState(TypedDict, total=False):
    run_id: str
    status: str
    user_request: str
    original_user_request: str
    web_search_mode: str
    research: dict[str, Any]
    request_type: str
    assumptions: list[str]
    blocking_questions: list[str]
    question_forms: dict[str, Any]
    awaiting_input_reason: Literal['interview', 'review'] | None
    review_questions: list[dict[str, Any]]
    review_history: list[dict[str, Any]]
    resolution_history: list[dict[str, Any]]
    diagnosed_keys: list[str]
    resolution_stop: bool
    confirmed_user_sources: dict[str, str]
    reused_decisions: list[dict[str, Any]]
    interview_pre_answers: list[dict[str, Any]]
    requirement_lock: str
    requirement_lock_sheet: dict[str, Any] | None
    rubric: dict[str, Any]
    rubric_evaluation: dict[str, Any]
    rubric_summary: dict[str, Any]
    refinement: dict[str, Any]
    approval_acceptance: dict[str, Any]
    structured_issues: list[dict[str, Any]]
    critic_pass_count: int
    max_critic_passes: int
    approval_candidate_spec: str | None
    final_agent_spec: str | None
    latest_completed: dict[str, str] | None
    critical_report: str | None
    user_approval_status: str
    revision_feedback: str
    revision_history: list[str]
    created_artifacts: list[str]
    workflow_schema: int
    revision: int
    plan: dict[str, Any]
    plan_history: list[dict[str, Any]]
    task_results: list[dict[str, Any]]
    task_messages: dict[str, list[dict[str, Any]]]
    knowledge_context: dict[str, Any]
    completed_tasks: list[str]
    remaining_steps: RemainingSteps
    execution_segment: int
    execution_diagnostic: dict[str, Any]
    execution_constraints: dict[str, Any]
    wait_reason: str
    stop_reason: str
    final_resolution_keys: list[str]
    allowed_actions: list[str]
    candidate_hash: str
    document_versions: list[dict[str, Any]]
    pending_input: dict[str, Any]
    mcp: dict[str, Any]
    _interview_direction_changing: bool


STAGE_SCHEMAS: dict[str, type[BaseModel]] = {
    "rubric_generate": RubricResponse,
    "interview": InterviewResponse,
    "requirement_lock": LockResponse,
    "spec_compile": SpecDraftResponse,
    "checklist_critic": ReviewResponse,
    "review_resolution": ReviewResolutionResponse,
}


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def count_unresolved_blocking(issues: list[IssuePacket]) -> int:
    return sum(1 for i in issues if i.blocking and i.status != "resolved")


def count_unresolved_required(issues: list[IssuePacket]) -> int:
    """심각도와 무관하게 미확정·미반영 사용자 결정도 승인 필수 항목으로 센다."""
    return sum(
        1
        for issue in issues
        if (issue.severity in {"blocking", "major"} or issue.resolution_kind == "user_decision" or issue.decision_answer_id)
        and issue.status != "resolved"
    )


def merge_issue_lists(
    base: list[IssuePacket],
    additional: list[IssuePacket],
) -> list[IssuePacket]:
    """같은 검토 항목을 합치되 별도 사용자 결정은 심각도와 무관하게 보존한다."""
    merged = list(base)
    for issue in additional:
        matching = next(
            (item for item in merged if item.checklist_id == issue.checklist_id and item.requirement_id == issue.requirement_id
             and item.decision_key.casefold() == issue.decision_key.casefold()
             and item.resolution_kind == issue.resolution_kind
             and (issue.resolution_kind == "auto_fix" or item.decision_question == issue.decision_question)), None
        )
        if matching is None:
            merged.append(issue)
        elif _SEVERITY_RANK.get(issue.severity, -1) > _SEVERITY_RANK.get(
            matching.severity, -1
        ):
            issue.rubric_ids = list(dict.fromkeys([*matching.rubric_ids, *issue.rubric_ids]))
            merged[merged.index(matching)] = issue
        else:
            matching.rubric_ids = list(dict.fromkeys([*matching.rubric_ids, *issue.rubric_ids]))
    return merged


def normalize_severity(value: Any, *, default: str = "major") -> str:
    s = str(value or default).lower().strip()
    return s if s in VALID_SEVERITY else default


def parse_issue_list(data: Any) -> list[IssuePacket]:
    """Parse a provider response into IssuePacket list.

    Accepts dict with "issues" key, or a raw list.
    Returns empty list if data is missing or malformed (relies on deterministic
    checks as the authoritative source of blocking issues).
    """
    if data is None:
        return []
    if isinstance(data, dict):
        raw = data.get("issues", [])
    elif isinstance(data, list):
        raw = data
    else:
        return []
    if not isinstance(raw, list):
        return []
    result: list[IssuePacket] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        result.append(IssuePacket.from_dict(item, fallback_id=f"ISSUE-{i:03d}"))
    return result
