"""제공자 호출의 사용량을 산출물에 안전하게 기록한다."""

from __future__ import annotations

from protocol.logging import get_logger
from contextvars import ContextVar
from hashlib import sha256
import json
import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from backend.infrastructure.model_policy import POLICY
from backend.models import STAGE_SCHEMAS
from backend.infrastructure.output_language import LANGUAGE_RULES, language_issues, OutputLanguageError

from backend.infrastructure.cache_diagnostics import safe_response_id, safe_diagnostics
from backend.knowledge.core import Documents
from backend.models import CompletionResult
from backend.providers.llm_provider import ChatModelProvider
from backend.infrastructure.stage_retry import attempt_limit, current_messages, retry_messages
from backend.infrastructure.prompt_context import prepare_context
from backend.infrastructure.conversation_state import cache_key, call_started, call_finished, job_conversation
from backend.errors import RequirementNormalizationError, ReviewValidationError, SpecCompilationError


LOGGER = get_logger("backend.server")
WORKFLOW_MESSAGES = ContextVar("workflow_messages", default=None)


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
    usage = _load_usage(writer)
    attempt = {
        "stage": _safe_stage(stage),
        "provider": _safe_provider(provider),
        "model": _safe_model(model),
        "status": "attempt",
        "elapsed_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
    }
    attempts = usage.setdefault("attempts", [])
    attempt["run_id"] = writer.job_id
    if not isinstance(attempts, list):
        attempts = []
        usage["attempts"] = attempts
    now = datetime.now(timezone.utc)
    baseline = next((item for item in reversed(attempts)
                     if item.get("status") == "success"
                     and all(item.get(key) == attempt[key] for key in ("provider", "model", "stage"))
                     and safe_response_id(item.get("response_id"))), None)
    # 현재 어댑터에서 진단 옵션을 지원하는 호출만 비교한다.
    if attempt["provider"] != "openai" or not re.match(r"^gpt-6(?:[.-]|$)", model.strip(), re.IGNORECASE):
        baseline = None
    baseline_time = _utc_time(baseline.get("started_at")) if baseline else None
    attempt.update(
        started_at=now.isoformat(),
        response_id=None,
        comparison_response_id=baseline["response_id"] if baseline else None,
        comparison_elapsed_ms=max(0, round((now - baseline_time).total_seconds() * 1000)) if baseline_time else None,
        cache_diagnostics=None,
    )
    attempts.append(attempt)
    _record_usage(writer, usage)
    LOGGER.info(
        "provider call stage=%s provider=%s model=%s status=attempt "
        "elapsed_ms=unknown input_tokens=unknown output_tokens=unknown cached_tokens=unknown",
        attempt["stage"],
        attempt["provider"],
        attempt["model"],
    )

    started = perf_counter()
    try:
        schema = isolated_schema or STAGE_SCHEMAS.get(stage)
        version = sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        instructions = "\n\n".join([
            f"Current stage: {stage}. Current input version: {version}. "
            "Apply these stage instructions only to this call. Use only the current call's allowed source references; "
            "older outputs and superseded drafts are historical data. Return the current output schema only.",
            *(item["content"] for item in messages if item.get("role") in {"system", "developer"}
              and item["content"] != POLICY), LANGUAGE_RULES.get(stage, "")])
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
            raise TypeError("Provider structured result is invalid.")
        if not isinstance(result, CompletionResult):
            raise TypeError("Provider completion result is invalid.")
    except Exception as exc:
        failed_result = getattr(exc, "completion", None)
        if isinstance(failed_result, CompletionResult):
            if safe_response_id(failed_result.response_id):
                call_finished(writer, provider, failed_result)
            attempt.update(input_tokens=_count(failed_result.input_tokens),
                           output_tokens=_count(failed_result.output_tokens),
                           cached_tokens=_count(failed_result.cached_tokens))
        attempt.update(status="failed", elapsed_ms=_elapsed_ms(started))
        _record_usage(writer, usage)
        LOGGER.info(
            "provider call stage=%s provider=%s model=%s status=failed "
            "elapsed_ms=%s input_tokens=unknown output_tokens=unknown cached_tokens=unknown",
            attempt["stage"],
            attempt["provider"],
            attempt["model"],
            attempt["elapsed_ms"],
        )
        raise

    attempt.update(
        status="success",
        elapsed_ms=_elapsed_ms(started),
        input_tokens=_count(result.input_tokens),
        output_tokens=_count(result.output_tokens),
        cached_tokens=_count(result.cached_tokens),
        response_id=safe_response_id(result.response_id),
        cache_diagnostics=safe_diagnostics(result.cache_diagnostics),
    )
    _record_usage(writer, usage)
    LOGGER.info(
        "provider call stage=%s provider=%s model=%s status=success "
        "elapsed_ms=%s input_tokens=%s output_tokens=%s cached_tokens=%s",
        attempt["stage"],
        attempt["provider"],
        attempt["model"],
        attempt["elapsed_ms"],
        _logged_count(attempt["input_tokens"]),
        _logged_count(attempt["output_tokens"]),
        _logged_count(attempt["cached_tokens"]),
    )
    diagnostic = attempt["cache_diagnostics"] or {}
    LOGGER.info(
        "provider cache stage=%s model=%s type=%s reason=%s cached_tokens=%s",
        attempt["stage"], attempt["model"], diagnostic.get("type", "unknown"),
        diagnostic.get("reason", "unknown"), _logged_count(attempt["cached_tokens"]),
    )
    if isolated_schema is not None:
        return result.parsed
    return references.restore(result.parsed) if schema else result.text


def _load_usage(writer: Documents) -> dict[str, Any]:
    return writer.usage()


def _record_usage(writer: Documents, usage: dict[str, Any]) -> bool:
    try:
        writer.save_usage(usage)
    except Exception as exc:
        usage["recording_incomplete"] = True
        _log_usage_io("write", exc)
        return False
    return True


def _safe_stage(stage: object) -> str:
    if not isinstance(stage, str):
        return "unknown"
    return stage if stage.replace("_", "").isalnum() and len(stage) <= 64 else "unknown"


def _safe_provider(provider: ChatModelProvider) -> str:
    name = getattr(provider, "provider_name", "unknown")
    return name if isinstance(name, str) and name.isidentifier() else "unknown"


def _safe_model(model: object) -> str:
    if not isinstance(model, str):
        return "unknown"
    cleaned = model.replace("-", "").replace(".", "")
    return model if cleaned.isalnum() and len(model) <= 128 else "unknown"


def _count(value: int | None) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _logged_count(value: int | None) -> int | str:
    return value if value is not None else "unknown"


def _log_usage_io(operation: str, exc: BaseException) -> None:
    LOGGER.warning(
        "provider usage %s failed exception_type=%s",
        operation,
        type(exc).__name__,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _utc_time(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None
