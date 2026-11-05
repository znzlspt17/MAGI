"""명세 검토의 정상 완료와 루브릭 복구에 따른 상태 전이 규칙."""

from backend.errors import ReviewValidationError

REVIEW_TASKS = frozenset({"checklist_critic", "review_resolution", "compose_candidate"})
COMPILATION_REVIEW_TASKS = REVIEW_TASKS | {"spec_compile"}
COMPLETION_INVALIDATIONS = {
    "interview": COMPILATION_REVIEW_TASKS | {"requirement_lock_stage"},
    "requirement_lock_stage": COMPILATION_REVIEW_TASKS,
    "spec_compile": REVIEW_TASKS,
    "checklist_critic": frozenset({"review_resolution", "compose_candidate"}),
}


def retry_upgrade_reason(action, old_policy, current_policy, requires_replay, has_next):
    """2026-11-05: 미확정 호출은 재생 동의 경계를 우회해 정책 복구하지 않는다."""
    if action == "retry" and old_policy is not None and old_policy != current_policy and not requires_replay and has_next:
        return "rubric_input_changed"
    return None


def failed_review_recovery_reason(error):
    if (isinstance(error, ReviewValidationError) and error.failed_checks == ["rubric_stale"]
            and error.validation_reason != "recovery_exhausted"):
        return error.validation_reason or "rubric_input_changed"
    return None


def recovery_invalidated_tasks(reason):
    if reason == "rubric_input_changed":
        return COMPILATION_REVIEW_TASKS
    return REVIEW_TASKS
