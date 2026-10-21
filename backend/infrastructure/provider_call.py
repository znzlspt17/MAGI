"""제공자 호출의 사용량을 산출물에 안전하게 기록한다."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from backend.infrastructure.conversation_state import ConversationState
from backend.models import STAGE_SCHEMAS
from backend.infrastructure.output_language import LANGUAGE_RULES, language_issues, OutputLanguageError

from backend.infrastructure.cache_diagnostics import safe_response_id, safe_diagnostics
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.models import CompletionResult
from backend.providers.llm_provider import OpenAIProvider
from backend.infrastructure.stage_retry import attempt_limit, current_messages, retry_messages
from backend.infrastructure.prompt_context import prepare_context
from backend.errors import RequirementNormalizationError, ReviewValidationError, SpecCompilationError


LOGGER = logging.getLogger("backend.server")
_USAGE_PATH = "state/provider_usage.json"
_CACHE_KEY_VERSION = "v2"


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


def complete_direct(provider, messages, *, model, stage):
    schema = STAGE_SCHEMAS[stage]
    messages = current_messages(messages, stage)
    original_messages = list(messages)
    limit = attempt_limit()
    for attempt in range(limit):
        projected, references = prepare_context(None, messages, stage)
        result = provider.complete_result(projected, model=model, temperature=0, text_format=schema,
            instructions="\n\n".join(item["content"] for item in projected if item.get("role") == "system")
                         + "\n" + LANGUAGE_RULES[stage]).parsed
        if not isinstance(result, schema):
            raise TypeError("Provider structured result is invalid.")
        try:
            result = references.restore(result)
        except (RequirementNormalizationError, ReviewValidationError, SpecCompilationError) as exc:
            if attempt == limit - 1:
                raise
            messages = retry_messages(original_messages, stage=stage, attempt=attempt + 1, error=exc)
            continue
        details = language_issues(result)
        if not details:
            return result
        if attempt == limit - 1:
            raise OutputLanguageError(details)
        messages = retry_messages(original_messages, stage=stage, attempt=attempt + 1, error=OutputLanguageError(details))
    raise AssertionError("Unreachable language repair")


def _complete_once(
    writer: ArtifactWriter,
    provider: OpenAIProvider,
    messages: list[dict],
    *,
    model: str,
    stage: str,
    temperature: float | None = 0,
    isolated_schema: type | None = None,
) -> Any:
    """사용량과 대화 연결을 저장하고 단계별 구조화 결과를 전달한다."""
    # 변경 검토는 생성 대화와 검색 문맥을 공유하지 않는 단발 호출이다.
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
    state_path = writer.path("state/state.json")
    attempt["run_id"] = writer.read_json("state/state.json").get("run_id") if state_path.exists() else None
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
        conversation = ConversationState(writer) if schema and isolated_schema is None else None
        extra = {"text_format": isolated_schema} if isolated_schema else {}
        if conversation:
            is_new = not conversation.conversation_id
            if is_new and any(item.get("run_id") == attempt["run_id"] and item.get("conversation_event") in {"started", "continued"} for item in attempts[:-1]):
                from backend.errors import ConversationUnavailableError
                raise ConversationUnavailableError("Conversation state is missing. Start a new generation.")
            conversation.ensure(provider)
            instructions, inputs, fingerprints = conversation.prepare(messages, stage)
            extra = dict(instructions=instructions + "\n\n" + LANGUAGE_RULES[stage], text_format=schema,
                         conversation_id=conversation.conversation_id)
            conversation.begin()
        else:
            inputs = messages
        result = provider.complete_result(
            inputs, model=model, temperature=temperature, cache_key=_cache_key(stage),
            comparison_response_id=attempt["comparison_response_id"], **extra,
        )
        if conversation:
            if not isinstance(result.parsed, schema):
                raise TypeError("Provider structured result is invalid.")
            conversation.commit(result.response_id, fingerprints, model=model, stage=stage)
            attempt["conversation_event"] = "started" if is_new else "continued"
        if not isinstance(result, CompletionResult):
            raise TypeError("Provider completion result is invalid.")
    except Exception:
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


def _load_usage(writer: ArtifactWriter) -> dict[str, Any]:
    if not writer.path(_USAGE_PATH).exists():
        return {"attempts": [], "recording_incomplete": False}
    try:
        value = writer.read_json(_USAGE_PATH)
    except Exception as exc:
        _log_usage_io("read", exc)
        return {"attempts": [], "recording_incomplete": True}
    if not isinstance(value, dict) or not isinstance(value.get("attempts"), list):
        LOGGER.warning(
            "provider usage read failed reason=invalid_data exception_type=none"
        )
        return {"attempts": [], "recording_incomplete": True}
    return {
        "attempts": [
            _normalise_attempt(item)
            for item in value["attempts"]
            if isinstance(item, dict)
        ],
        "recording_incomplete": value.get("recording_incomplete") is True,
    }


def _record_usage(writer: ArtifactWriter, usage: dict[str, Any]) -> bool:
    try:
        writer.write_json(_USAGE_PATH, usage, overwrite=True)
    except Exception as exc:
        usage["recording_incomplete"] = True
        _log_usage_io("write", exc)
        return False
    return True


def _cache_key(stage: str) -> str:
    return f"{_CACHE_KEY_VERSION}:{_safe_stage(stage)}:v2"


def _safe_stage(stage: object) -> str:
    if not isinstance(stage, str):
        return "unknown"
    return stage if stage.replace("_", "").isalnum() and len(stage) <= 64 else "unknown"


def _safe_provider(provider: OpenAIProvider) -> str:
    name = getattr(provider, "provider_name", "unknown")
    return name if isinstance(name, str) and name.isidentifier() else "unknown"


def _safe_model(model: object) -> str:
    if not isinstance(model, str):
        return "unknown"
    cleaned = model.replace("-", "").replace(".", "")
    return model if cleaned.isalnum() and len(model) <= 128 else "unknown"


def _count(value: int | None) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _normalise_attempt(value: dict[str, Any]) -> dict[str, Any]:
    status = value.get("status")
    return {
        "stage": _safe_stage(value.get("stage", "")),
        "provider": value.get("provider")
        if value.get("provider") in {"openai"}
        else "unknown",
        "model": _safe_model(value.get("model", "")),
        "status": status if status in {"attempt", "success", "failed"} else "attempt",
        "elapsed_ms": _count(value.get("elapsed_ms")),
        "input_tokens": _count(value.get("input_tokens")),
        "output_tokens": _count(value.get("output_tokens")),
        "cached_tokens": _count(value.get("cached_tokens")),
        "started_at": timestamp.isoformat() if (timestamp := _utc_time(value.get("started_at"))) else None,
        "response_id": safe_response_id(value.get("response_id")),
        "comparison_response_id": safe_response_id(value.get("comparison_response_id")),
        "comparison_elapsed_ms": _count(value.get("comparison_elapsed_ms")),
        "cache_diagnostics": safe_diagnostics(value.get("cache_diagnostics")),
        "conversation_event": value.get("conversation_event") if value.get("conversation_event") in {"started", "continued"} else None,
    }


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
