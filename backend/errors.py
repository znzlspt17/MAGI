"""Domain errors raised by MAGI."""


from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.models import CompletionResult


class Error(Exception):
    """Base class for actionable MAGI errors."""

    completion: CompletionResult | None


class MissingCredentialError(Error):
    """Raised when a selected provider requires unavailable credentials."""


class ArtifactError(Error):
    """Raised when artifact persistence fails."""


class OutputLanguageError(Error):
    def __init__(self, details):
        super().__init__("Output language validation failed.")
        self.validation_details = details


class InvalidStateError(Error):
    """Raised when a saved run state is malformed or not ready."""


class RequirementNormalizationError(Error):
    """요구사항 잠금 응답을 안전하게 정규화할 수 없을 때 발생한다."""

    category: str
    validation_details: list[str]
    code = "REQUIREMENT_NORMALIZATION_FAILED"
    stage = "requirement_lock"


class PermissionDeniedError(Error):
    """Raised when an agent tries to use a skill outside its permission set."""


class ReviewValidationError(Error):
    """검토 응답 오류를 제품 명세 결함과 구분한다."""

    code = "REVIEW_VALIDATION_FAILED"
    stages = frozenset({"interview", "requirement_lock", "spec_compile", "checklist_critic", "review_resolution", "rubric_generate", "compose_candidate"})
    checks = frozenset({"review_response", "source_reference", "review_requirement", "review_evidence",
                        "review_classification", "decision_key", "resolution_schema", "resolution_coverage",
                        "resolution_language", "resolution_basis", "resolution_question", "resolution_auto_fix",
                        "resolution_reconfirmation", "question_text", "question_form", "question_pending",
                        "rubric_schema", "rubric_identity", "rubric_basis", "rubric_boundary", "rubric_coverage",
                        "rubric_evaluation_coverage", "rubric_evidence", "rubric_issue", "rubric_stale", "rubric_score"})

    reasons = frozenset({"rubric_input_changed", "evaluation_missing", "evaluation_draft_mismatch",
                         "stored_evaluation_invalid", "recovery_exhausted", "quote_not_found",
                         "section_invalid", "reason_missing", "evaluation_coverage_mismatch",
                         "issue_link_invalid", "score_invalid", "requirement_unknown", "condition_missing",
                         "importance_invalid", "basis_reference_invalid", "basis_quote_not_found", "rubric_coverage_missing"})

    def __init__(self, details=None, *, stage="checklist_critic", check="review_response", reason=None, context=None):
        super().__init__("Checklist review response could not be validated.")
        self.validation_details = details or ["Return a valid complete checklist review response."]
        self.stage = stage if isinstance(stage, str) and stage in self.stages else "checklist_critic"
        self.failed_checks = [check if isinstance(check, str) and check in self.checks else "review_response"]
        self.validation_reason = reason if reason in self.reasons else None
        self.validation_context = context if isinstance(context, dict) else {}


class WorkflowPersistenceError(Error):
    """업무 결과의 영속 저장 실패를 모델 응답 오류와 구분한다."""


class WorkflowExecutionUncertain(Error):
    """외부 호출의 완료 여부가 확인되지 않아 재실행 동의가 필요하다."""


class SpecCompilationError(Error):
    """명세 응답의 검증 실패를 보정·공개 진단 경로로 전달한다."""

    validation_phase: str
    validation_location: dict[str, str | int]

    code = "SPEC_COMPILATION_INVALID"
    stage = "spec_compile"
    checks = frozenset({"spec_response", "implementation_plan", "spec_blocks", "spec_links",
                        "decision_trace", "source_reference", "product_boundary", "spec_structure",
                        "quote_anchor"})
    block_reasons = frozenset({"empty_section", "invalid_item_id", "empty_item_id", "duplicate_item_id", "reserved_item_id", "empty_text",
                               "unknown_requirement", "unknown_decision", "fixed_heading"})

    block_fields = frozenset({"item_id", "text", "requirement_ids", "decision_ids"})

    def __init__(self, details, *, check="spec_response", block_reason=None, section=None, index=None, field=None):
        super().__init__("Compiler response trace could not be validated.")
        self.validation_details = details
        self.failed_checks = [check if isinstance(check, str) and check in self.checks else "spec_response"]
        self.block_reason = block_reason if isinstance(block_reason, str) and block_reason in self.block_reasons else None
        self.block_section, self.block_index = section, index
        self.block_field = field if isinstance(field, str) and field in self.block_fields else None
