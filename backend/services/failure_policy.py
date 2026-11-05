"""단계 보정, 저널 상태, 공개 진단의 서로 다른 실패 판정 기준."""

from backend.errors import (
    Error, InvalidStateError, RequirementNormalizationError, ReviewValidationError,
    SpecCompilationError, WorkflowExecutionUncertain, WorkflowPersistenceError, OutputLanguageError,
)


VALIDATION_ERRORS = (RequirementNormalizationError, ReviewValidationError, SpecCompilationError, OutputLanguageError)
UNCERTAIN_MESSAGES = frozenset({
    "이전 작업 호출의 완료 여부를 확인할 수 없습니다. 호출 반복 가능성에 동의한 뒤 미완료 단계를 다시 실행하세요.",
    "이전 OpenAI 호출의 완료 여부를 확인할 수 없습니다. 호출 반복 가능성에 동의한 뒤 다시 실행하세요.",
    "OpenAI 대화 생성 완료 여부를 확인할 수 없습니다. 자동 재생성을 중단했습니다.",
    "OpenAI 대화 초기 문맥 저장 완료 여부를 확인할 수 없습니다. 자동 반복을 중단했습니다.",
    "OpenAI 대화 초기화 완료 여부를 확인할 수 없어 자동 반복을 중단했습니다.",
})


def correction_retryable(error: BaseException) -> bool:
    """2026-11-05: 상태 불일치는 응답 보정 대상이 아니며 예외 원인 체인을 추측하지 않는다."""
    return isinstance(error, VALIDATION_ERRORS) and not (
        isinstance(error, ReviewValidationError) and "rubric_stale" in error.failed_checks
    )


def journal_failure_category(error: BaseException, call_count: int) -> str:
    """상태 불일치도 완료된 검증 실패로 기록해 불필요한 재실행 동의를 피한다."""
    if isinstance(error, WorkflowPersistenceError):
        return "persistence_failed"
    if isinstance(error, VALIDATION_ERRORS):
        return "validation"
    return "not_called" if not call_count else "call_uncertain"


def diagnostic_category(chain: list[BaseException]) -> str | None:
    """공개 분류는 체인 전체를 보며 미확정 > 저장 > 검토 > 기타 검증 순이다."""
    if any(isinstance(item, WorkflowExecutionUncertain) or
           (isinstance(item, (InvalidStateError, Error)) and len(item.args) == 1
            and isinstance(item.args[0], str) and item.args[0] in UNCERTAIN_MESSAGES) for item in chain):
        return "execution_uncertain"
    if any(isinstance(item, WorkflowPersistenceError) for item in chain):
        return "persistence_failed"
    review = next((item for item in chain if isinstance(item, ReviewValidationError)), None)
    if review is not None:
        return "prerequisite_stale" if "rubric_stale" in review.failed_checks else "response_invalid"
    if any(isinstance(item, (RequirementNormalizationError, SpecCompilationError, OutputLanguageError)) for item in chain):
        return "response_invalid"
    return None
