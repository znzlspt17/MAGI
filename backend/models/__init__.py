"""MAGI의 데이터 클래스와 구조화 응답 계약."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

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
    impact: str | None = Field(default=None, min_length=1, max_length=240, description="Korean conditional impact, including relevant benefits and burdens. Advisory, never a user decision.")
    assumptions: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=3, description="Korean conditions under which the impact applies; not confirmed requirements.")


class QuestionRecommendation(ResponseModel):
    option_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=300, description="Korean recommendation rationale grounded in supplied context, never user approval.")
    assumptions: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=3)


class QuestionFormSpec(ResponseModel):
    input_type: Literal["text", "single_choice", "multiple_choice"] = "text"
    options: list[QuestionOption] = Field(default_factory=list)
    recommendation: QuestionRecommendation | None = Field(default=None, description="Optional advice. Use null when priorities or context are insufficient; never preselect an answer.")

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
    question: str = Field(description='Korean question. Preserve an existing quoted user question verbatim.')


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
    text: str = Field(description='Normalized English assumption; keep risk enum unchanged.')
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
    quote: str = Field(description='Exact evidence excerpt in its original language, without translation.')


class InterviewResponse(ResponseModel):
    request_type: Literal["product", "feature", "bugfix", "refactor", "infra"]
    assumptions: list[str] = Field(description='Korean explanations of unconfirmed assumptions.')
    blocking_questions: list[QuestionResponse] = Field(description='Korean questions requiring a user decision.')
    additional_questions: list[QuestionResponse] = Field(description='Korean additional questions.')
    pre_answers: list[AnswerResponse] = Field(description='Saved user answers preserved verbatim without translation.')


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
        )


class IssueResponse(ResponseModel):
    decision_form: QuestionFormSpec | None = None
    defect_kind: Literal["requirements_gap", "spec_omission", "verification_gap", "confirmed_conflict"]
    resolution_reason: str = Field(description="Korean explanation grounded in confirmed inputs.")
    missing_information: str = Field(description="Korean description of a missing material choice and its impact; empty if nothing is missing.")
    decision_key: str = Field(description="Stable English decision topic identifier, reused across changed wording or severity. Do not include a question sentence.")
    section: str
    severity: Literal["blocking", "major", "minor"]
    checklist_id: str
    problem: str = Field(description='Korean explanation of the defect.')
    required_change: str = Field(description='Korean explanation of the required fix. Quote proposed English specification wording verbatim.')
    requirement_id: str | None
    evidence: list[EvidenceResponse]
    resolution_kind: Literal["auto_fix", "user_decision"] = Field(default="auto_fix", description='Independent of severity. Use user_decision only for a material choice not answered by confirmed inputs.')
    decision_question: str | None = Field(default=None, description='Required Korean question for user_decision; otherwise null. Use identical wording for the same decision across issues and passes.')


class LockResponse(ResponseModel):
    decisions: list[DecisionTrace] = Field(default_factory=list, description='Explicit choices with stable IDs, exact user quotes for actor=user, and verified source/requirement IDs. Reuse must remain actor=llm.')
    request_summary: str = Field(description='Korean summary of the user request.')
    mandatory_requirements: list[RequirementResponse]
    recommended_requirements: list[RequirementResponse]
    optional_requirements: list[RequirementResponse]
    non_scope: list[RequirementResponse]
    workflow_constraints: list[WorkflowConstraintResponse] = Field(description="User requests about MAGI operation only, separate from target-product requirements. Required array, empty when none were supplied; WF-* IDs and exact verified user quotations.")
    assumptions: list[AssumptionResponse]
    constraints: list[RequirementResponse]
    acceptance_criteria_seed: list[str] = Field(description='Observable English acceptance criteria citing requirement IDs.')
    unresolved_questions: list[str] = Field(description='Korean unresolved questions; must be empty after interview resolution.')


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
    # critic stage
    structured_issues: list[dict[str, Any]] = field(default_factory=list)
    critic_pass_count: int = 0
    max_critic_passes: int = 3
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
    segment_steps: int = 0
    execution_segment: int = 0
    execution_constraints: dict[str, Any] = field(default_factory=dict)
    wait_reason: str = ""
    stop_reason: str = ""
    final_resolution_keys: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    candidate_hash: str = ""
    document_versions: list[dict[str, Any]] = field(default_factory=list)
    pending_input: dict[str, Any] = field(default_factory=dict)

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
    def from_dict(cls, data: dict[str, Any]) -> "RequirementLockSheet":
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
    text: str = Field(description='Normalized English requirement text.')
    source: str
    original_text: str = Field(description='Exact original user wording, without translation; empty when not applicable.')
    sources: list[str]


class WorkflowConstraintResponse(RequirementResponse):
    original_text: str = Field(description="Exact nonempty quotation from the cited actual user input describing how MAGI should work, not target-product behavior.")


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
    conflicting_source: str | None = Field(description="Supplied S reference for current user feedback only when a NEW user request conflicts with an already answered decision; otherwise null.")


class ReviewResolutionResponse(ResponseModel):
    resolutions: list[ResolutionItem]


class ReviewResponse(ResponseModel):
    issues: list[IssueResponse]


class SpecTranslationResponse(ResponseModel):
    content: str = Field(description='Complete Korean Markdown translation of the supplied specification. Preserve structure, IDs, numbers, code and original quotations.')


class SpecResponse(ResponseModel):
    decisions: list[DecisionTrace] = Field(default_factory=list, description='Additional explicit LLM choices. Preserve existing decision IDs in links rather than redeclaring them. Include application rationale and reused_node_ids for adopted references.')
    spec_links: list[SpecLink] = Field(default_factory=list, description='Canonical links constructed by the application from generated content blocks. Quotes are actual rendered source text.')
    mission: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    background: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    user_intent: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    in_scope: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    out_of_scope: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    definitions: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    evidence_summary: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    recommended_requirements: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    optional_requirements: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    forbidden_behaviors: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    input_contract: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    output_contract: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    architecture: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    module_responsibilities: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    data_flow: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    error_handling_policy: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    configuration_policy: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    persistence_artifact_policy: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    implementation_order: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    acceptance_criteria: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    test_plan: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    manual_verification_checklist: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")
    instructions_for_ai_coding_agent: str = Field(description="English section prose. Preserve code, paths and explicitly marked original quotations.")

    def markdown(self) -> str:
        """고정 heading과 잠금 섹션은 모델이 생성하지 않는다."""
        from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS

        fields = iter(value for key, value in self.model_dump().items() if key not in {"decisions", "spec_links"})
        sections = []
        for heading in REQUIRED_FINAL_SPEC_HEADINGS:
            if heading in {"# Final Agent Specification", "## 4. Scope", "## 7. Mandatory Requirements"}:
                sections.append(heading)
            else:
                sections.append(heading + "\n\n" + next(fields))
        return "\n\n".join(sections) + "\n"


class SpecBlock(ResponseModel):
    """명세 본문과 연결 정보를 한 번만 생성하는 출력 단위."""

    item_id: str = Field(description="Unique stable block ID across all sections. Never use the reserved LOCKED- prefix.")
    text: str = Field(description="The actual English paragraph, list, table or code block to render. Do not repeat this text elsewhere as a quotation.")
    requirement_ids: list[str] = Field(description="Only requirement IDs from the supplied lock sheet that this block operationalizes.")
    decision_ids: list[str] = Field(description="Only supplied lock decisions or additional decisions declared in this response.")


class ImplementationTask(SpecBlock):
    title: str = Field(description="Short English implementation task title.")
    depends_on: list[str] = Field(description="Predecessor task item IDs; no cycles or self reference.")
    spec_item_ids: list[str] = Field(min_length=1, description="Actual behavior block IDs in this response, outside implementation_order and verification sections.")
    completion_item_ids: list[str] = Field(min_length=1, description="Existing block IDs in acceptance_criteria, test_plan or manual_verification_checklist.")


# 저장·조회 형식인 SpecResponse는 유지하고 제공자 출력만 블록 구조로 분리한다.
SpecDraftResponse = create_model("SpecDraftResponse", __base__=ResponseModel,
    decisions=(list[DecisionTrace], Field(default_factory=list)),
    **{name: (list[ImplementationTask] if name == "implementation_order" else list[SpecBlock], Field(description=(
        "Application-owned section assembled from locked product non_scope. Return an empty array; do not generate content or references."
        if name == "out_of_scope" else "Ordered substantive English content blocks for this section. Include at least one block.")))
       for name in SpecResponse.model_fields if name not in {"decisions", "spec_links"}})


def assemble_spec_draft(draft, sheet, task_plan=None):
    """실제 출력 본문에서만 인용을 만들고 기존 명세·추적 형식으로 변환한다."""
    from backend.errors import SpecCompilationError
    from backend.knowledge.trace import REQUIREMENT_GROUPS
    from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS, _mask_fenced_code
    known_requirements = {item["id"] for group in REQUIREMENT_GROUPS for item in sheet.to_dict().get(group, [])}
    known_decisions = {item["id"] for item in sheet.decisions} | {item.id for item in draft.decisions}
    headings = set(REQUIRED_FINAL_SPEC_HEADINGS) | {"### Locked Constraints"}
    from backend.services.implementation_plan import prepare_plan
    task_plan = task_plan or prepare_plan(draft, sheet)
    sections, links, identities = {}, [], set()
    for name in SpecResponse.model_fields:
        if name in {"decisions", "spec_links"}:
            continue
        if name == "out_of_scope":
            # 앱이 교체하는 모델 블록은 ID·내용 검증이나 구현 근거에 사용하지 않는다.
            sections[name] = "\n".join(f"- [{item.id}] {item.text}" for item in sheet.non_scope) or "No explicit product exclusions were supplied."
            links.extend(SpecLink(item_id="LOCKED-" + item.id, section=name, quote=item.text,
                                  requirement_ids=[item.id], decision_ids=[]) for item in sheet.non_scope)
            continue
        blocks = getattr(draft, name)
        if name == "implementation_order":
            blocks = [SpecBlock(item_id=t["item_id"], text=t["rendered"], requirement_ids=t["requirement_ids"], decision_ids=t["decision_ids"]) for t in task_plan["tasks"]]
        if not blocks:
            raise SpecCompilationError([f"{name}: include at least one substantive content block."], check="spec_blocks",
                                       block_reason="empty_section", section=name)
        for index, block in enumerate(blocks):
            if not block.item_id.strip() or block.item_id in identities or block.item_id.startswith("LOCKED-"):
                raise SpecCompilationError([f"{name}[{index}].item_id: use a unique nonempty stable ID without the LOCKED- prefix."], check="spec_blocks",
                                           block_reason="invalid_item_id", section=name, index=index)
            identities.add(block.item_id)
            if not block.text.strip():
                raise SpecCompilationError([f"{name}[{index}].text: include substantive English content."], check="spec_blocks",
                                           block_reason="empty_text", section=name, index=index)
            if not set(block.requirement_ids) <= known_requirements:
                raise SpecCompilationError([f"{name}[{index}].requirement_ids: use only supplied requirement IDs."], check="spec_blocks",
                                           block_reason="unknown_requirement", section=name, index=index)
            if not set(block.decision_ids) <= known_decisions:
                raise SpecCompilationError([f"{name}[{index}].decision_ids: use only known decision IDs."], check="spec_blocks",
                                           block_reason="unknown_decision", section=name, index=index)
            if any(line.strip() in headings for line in _mask_fenced_code(block.text).splitlines()):
                raise SpecCompilationError([f"{name}[{index}].text: omit fixed section headings and Locked Constraints headings; the application renders them."], check="spec_blocks",
                                           block_reason="fixed_heading", section=name, index=index)
        sections[name] = "\n\n".join(block.text.rstrip() for block in blocks)
        links.extend(SpecLink(item_id=block.item_id, section=name, quote=block.text.rstrip(),
                              requirement_ids=block.requirement_ids, decision_ids=block.decision_ids)
                     for block in blocks if block.requirement_ids or block.decision_ids)
    return SpecResponse(decisions=draft.decisions, spec_links=links, **sections)


# 실행 상태의 필드 목록은 State 한 곳에서 정의한다.
from typing import get_type_hints
WorkflowState = TypedDict("WorkflowState", {**get_type_hints(State), "_interview_direction_changing": bool}, total=False)


STAGE_SCHEMAS = {
    "spec_translation": SpecTranslationResponse,
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
            merged[merged.index(matching)] = issue
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
