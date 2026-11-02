"""제공자 호출의 사용량을 산출물에 안전하게 기록한다."""

from __future__ import annotations

from backend.infrastructure.call_usage import CallUsage
from contextvars import ContextVar
from backend.infrastructure.provider_request import stage_instructions
from typing import Any

from backend.models import STAGE_SCHEMAS
from backend.infrastructure.output_language import language_issues, OutputLanguageError

from backend.infrastructure.cache_diagnostics import safe_response_id
from backend.knowledge.core import Documents
from backend.models import CompletionResult
from backend.providers.llm_provider import ChatModelProvider
from backend.infrastructure.stage_retry import attempt_limit, current_messages, retry_messages
from backend.infrastructure.prompt_context import prepare_context
from backend.infrastructure.conversation_state import cache_key, call_started, call_finished, job_conversation
from backend.errors import RequirementNormalizationError, ReviewValidationError, SpecCompilationError


WORKFLOW_MESSAGES: ContextVar[dict[str, list[dict]] | None] = ContextVar("workflow_messages", default=None)


def complete_with_usage(writer, provider, messages, *, model, stage, temperature=0):
    messages = current_messages(messages, stage)
    original_messages = list(messages)
    limit = attempt_limit()
    for attempt in range(limit):
        try:
            result = _complete_once(writer, provider, messages, model=model, stage=stage, temperature=temperature)
        except (RequirementNormalizationError, ReviewValidationError, SpecCompilationError) as exc:
            if attempt == limit - 1:
                raise
            messages = retry_messages(original_messages, stage=stage, attempt=attempt + 1, error=exc)
            continue
        # 요구사항 단계는 출처/보존 검증과 같은 보정 예산을 사용한다.
        details = [] if stage == "requirement_lock" else language_issues(result)
        if not details:
            return result
        if attempt == limit - 1:
            raise OutputLanguageError(details)
        messages = retry_messages(original_messages, stage=stage, attempt=attempt + 1, error=OutputLanguageError(details))
    raise AssertionError("Unreachable language repair")


def _complete_once(
    writer: Documents,
    provider: ChatModelProvider,
    messages: list[dict],
    *,
    model: str,
    stage: str,
    temperature: float | None = 0,
    isolated_schema: type | None = None,
) -> Any:
    with job_conversation(writer, provider) as conversation_id:
        return _complete_connected(writer, provider, messages, model=model, stage=stage,
                                   temperature=temperature, isolated_schema=isolated_schema,
                                   conversation_id=conversation_id)


def _complete_connected(writer, provider, messages, *, model, stage, temperature,
                        isolated_schema, conversation_id):
    """사용량과 작업별 메시지를 저장하고 단계별 구조화 결과를 전달한다."""
    # 별도 스키마의 전처리 경계와 원격 대화 수명주기는 독립적이다.
    references = None
    if isolated_schema is None:
        messages, references = prepare_context(writer, messages, stage)
    usage = CallUsage(writer, provider, model, stage)
    try:
        schema = isolated_schema or STAGE_SCHEMAS.get(stage)
        instructions = stage_instructions(messages, stage)
        recorder = WORKFLOW_MESSAGES.get()
        if recorder is not None:
            recorder[stage] = [{"role": "developer", "content": instructions},
                               *(item for item in messages if item.get("role") != "system")]
        callbacks = {}
        if isinstance(provider, ChatModelProvider):
            # 비용 예약·입력 준비 실패를 원격 호출 불확실성으로 기록하지 않는다.
            callbacks["before_request"] = lambda: call_started(writer, provider)
        else:
            from backend.infrastructure.workflow_store import provider_entered
            call_started(writer, provider)
            provider_entered()
        result = provider.complete_result(
            messages, model=model, temperature=temperature, cache_key=cache_key(writer.job_id),
            instructions=instructions, text_format=schema,
            conversation_id=conversation_id,
            **callbacks,
        )
        if isinstance(result, CompletionResult):
            call_finished(writer, provider, result)
        if schema is not None and not isinstance(result.parsed, schema):
            if stage in {"rubric_generate", "checklist_critic"}:
                raise ReviewValidationError(stage=stage, check="rubric_schema" if stage == "rubric_generate" else "review_response")
            raise TypeError("Provider structured result is invalid.")
        if not isinstance(result, CompletionResult):
            raise TypeError("Provider completion result is invalid.")
    except Exception as exc:
        failed_result = getattr(exc, "completion", None)
        if isinstance(failed_result, CompletionResult):
            if safe_response_id(failed_result.response_id):
                call_finished(writer, provider, failed_result)
            usage.record_failed_completion(failed_result)
        usage.failed()
        raise

    usage.succeeded(result)
    if isolated_schema is not None:
        return result.parsed
    if schema is not None:
        assert references is not None  # 일반 구조화 호출은 prepare_context를 반드시 거친다.
        return references.restore(result.parsed)
    return result.text
