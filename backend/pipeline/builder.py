"""계획형 그래프의 단계 실행·진행 이벤트."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from protocol.logging import get_logger
from backend.infrastructure.stage_retry import CURRENT_RETRY, MAX_RETRIES
from backend.services.failure_policy import correction_retryable


def _stage(name: str, node, callback, *, defer_completed: bool = False):
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
                retryable = correction_retryable(exc)
                from backend.server.diagnostics import diagnose_exception
                diagnostic = diagnose_exception(exc)
                if retryable:
                    # 원문 대신 허용된 검증 코드만 남겨 반복 실패 원인을 구분한다.
                    get_logger("backend.server").warning(
                        "stage_validation_failed", stage=name, attempt=attempt + 1,
                        max_attempts=MAX_RETRIES + 1, error_code=diagnostic["error_code"],
                        error_stage=diagnostic["error_stage"], failed_checks=diagnostic["failed_checks"],
                        exception_type=type(exc).__name__,
                        validation_reason=diagnostic["validation_reason"],
                        validation_section=diagnostic["validation_section"],
                        validation_index=diagnostic["validation_index"],
                        validation_field=diagnostic["validation_field"],
                    )
                if not retryable or attempt == MAX_RETRIES:
                    _progress(
                        callback,
                        name,
                        "failed",
                        {"diagnostic": diagnostic, **(
                            {"research": exc.research_record}
                            if name == "web_research" and hasattr(exc, "research_record") else {}
                        )},
                    )
                    raise
                _progress(
                    callback,
                    name,
                    "retrying",
                    {
                        "retry_attempt": attempt + 1,
                        "max_retries": MAX_RETRIES,
                        "diagnostic": diagnostic,
                        "summary": f"재시도 중… ({attempt + 1}/{MAX_RETRIES})",
                    },
                )
            finally:
                CURRENT_RETRY.reset(token)
        if not defer_completed:
            _progress(callback, name, "completed", result, state)
        return result

    return wrapped


def _progress(
    callback, stage: str, state: str, result: dict | None = None, workflow_state=None
) -> None:
    if callback is None:
        return
    event: dict[str, Any] = {"stage": stage, "state": state}
    if state == "retrying":
        from backend.application.execution_history import _safe_result
        data = result if isinstance(result, dict) else {}
        event["result"] = {key: data[key] for key in ("retry_attempt", "max_retries", "summary") if key in data}
        event["result"].update(_safe_result(data))
    if state in {"completed", "failed"} and isinstance(result, dict):
        # 실행 이력에는 상태 판단에 필요한 결과만 전달한다.
        from backend.application.execution_history import _safe_result
        event["result"] = _safe_result(result)
        if stage == "await_user" and "blocking_questions" not in event["result"]:
            questions = (
                workflow_state.get("blocking_questions", [])
                if isinstance(workflow_state, dict)
                else []
            )
            if isinstance(questions, list) and all(
                isinstance(item, str) for item in questions
            ):
                event["result"]["blocking_questions"] = questions
    callback(event)
