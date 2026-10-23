"""단계 실행·진행 이벤트와 이전 자료의 분기 해석."""

from __future__ import annotations

from typing import Literal
from copy import deepcopy
from backend.infrastructure.stage_retry import CURRENT_RETRY, MAX_RETRIES


from backend.models import count_unresolved_required, parse_issue_list
from backend.models import WorkflowState


def _stage(name: str, node, callback, *, checkpoint=None):
    def wrapped(state):
        _progress(callback, name, "started")
        error = None
        for attempt in range(MAX_RETRIES + 1):
            token = CURRENT_RETRY.set({"attempt": attempt, "error": error})
            try:
                result = node(deepcopy(state))
                break
            except Exception as exc:
                error = exc
                from backend.errors import RequirementNormalizationError, ReviewValidationError, SpecCompilationError
                from backend.infrastructure.output_language import OutputLanguageError
                retryable = isinstance(exc, (RequirementNormalizationError, ReviewValidationError, SpecCompilationError, OutputLanguageError))
                if not retryable or attempt == MAX_RETRIES:
                    _progress(callback, name, "failed", {"research": exc.research_record} if name == "web_research" and hasattr(exc, "research_record") else None)
                    raise
                _progress(callback, name, "retrying", {
                    "retry_attempt": attempt + 1,
                    "max_retries": MAX_RETRIES,
                    "summary": f"재시도 중… ({attempt + 1}/{MAX_RETRIES})",
                })
            finally:
                CURRENT_RETRY.reset(token)
        from backend.knowledge.runtime import CURRENT
        runtime = CURRENT.get()
        if checkpoint is not None:
            checkpoint(name, state, result)
        elif runtime is not None:
            runtime.commit(name, state, result)
        _progress(callback, name, "completed", result, state)
        return result

    return wrapped


def _progress(
    callback, stage: str, state: str, result: dict | None = None, workflow_state=None
) -> None:
    if callback is None:
        return
    try:
        event = {"stage": stage, "state": state}
        if state == "retrying":
            event["result"] = result
        if state in {"completed", "failed"} and isinstance(result, dict):
            # 실행 이력에는 상태 판단에 필요한 결과만 전달한다.
            event["result"] = {
                key: result[key]
                for key in (
                    "research",
                    "status",
                    "blocking_questions",
                    "structured_issues",
                    "critic_pass_count",
                    "request_type",
                    "awaiting_input_reason",
                    "review_questions",
                    "question_forms",
                    "resolution_history",
                    "diagnosed_keys",
                )
                if key in result
            }
            if stage == "await_user" and "blocking_questions" not in event["result"]:
                questions = workflow_state.get("blocking_questions", []) if isinstance(workflow_state, dict) else []
                if isinstance(questions, list) and all(isinstance(item, str) for item in questions):
                    event["result"]["blocking_questions"] = questions
        callback(event)
    except Exception:
        return


def route_after_interview(
    state: WorkflowState,
) -> Literal["requirement_lock_stage", "await_user"]:
    """Route after interview node."""
    if not state.get("user_request", "").strip():
        return "await_user"
    # If direction-changing blocking questions exist, pause for user input
    if state.get("blocking_questions") and state.get("_interview_direction_changing"):
        return "await_user"
    return "requirement_lock_stage"


def route_after_resolution(
    state: WorkflowState,
) -> Literal["compose_candidate", "spec_compile", "critical_report", "await_user"]:
    """해결 판단 결과와 남은 보완 예산으로 분기한다."""
    issues = parse_issue_list({"issues": state.get("structured_issues", [])})
    if any(issue.resolution_kind == "user_decision" and issue.status != "resolved" for issue in issues):
        from backend.errors import ReviewValidationError
        if state.get("awaiting_input_reason") != "review" or not state.get("blocking_questions"):
            raise ReviewValidationError(["User-decision issues require pending review questions."], stage="review_resolution", check="question_pending")
        return "await_user"
    unresolved = count_unresolved_required(issues)
    passes = int(state.get("critic_pass_count", 0))
    max_passes = int(state.get("max_critic_passes", 3))

    if unresolved == 0:
        return "compose_candidate"
    if passes < max_passes and not state.get("resolution_stop"):
        return "spec_compile"  # re-compile with issue feedback
    return "critical_report"  # exceeded max passes
