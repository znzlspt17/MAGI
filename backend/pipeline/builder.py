"""계획형 그래프의 단계 실행·진행 이벤트."""

from __future__ import annotations

from copy import deepcopy
from backend.infrastructure.stage_retry import CURRENT_RETRY, MAX_RETRIES


def _stage(name: str, node, callback):
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
                from backend.errors import (
                    RequirementNormalizationError,
                    ReviewValidationError,
                    SpecCompilationError,
                )
                from backend.infrastructure.output_language import OutputLanguageError

                retryable = isinstance(
                    exc,
                    (
                        RequirementNormalizationError,
                        ReviewValidationError,
                        SpecCompilationError,
                        OutputLanguageError,
                    ),
                )
                if not retryable or attempt == MAX_RETRIES:
                    _progress(
                        callback,
                        name,
                        "failed",
                        {"research": exc.research_record}
                        if name == "web_research" and hasattr(exc, "research_record")
                        else None,
                    )
                    raise
                _progress(
                    callback,
                    name,
                    "retrying",
                    {
                        "retry_attempt": attempt + 1,
                        "max_retries": MAX_RETRIES,
                        "summary": f"재시도 중… ({attempt + 1}/{MAX_RETRIES})",
                    },
                )
            finally:
                CURRENT_RETRY.reset(token)
        _progress(callback, name, "completed", result, state)
        return result

    return wrapped


def _progress(
    callback, stage: str, state: str, result: dict | None = None, workflow_state=None
) -> None:
    if callback is None:
        return
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
