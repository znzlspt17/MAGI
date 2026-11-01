"""모델 호출 사용량의 저장과 허용된 진단 필드 기록."""
from __future__ import annotations
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, TypedDict
import re
from protocol.logging import get_logger
from backend.infrastructure.cache_diagnostics import safe_response_id, safe_diagnostics
from backend.knowledge.core import Documents
from backend.models import CompletionResult
from backend.providers.llm_provider import ChatModelProvider

LOGGER = get_logger("backend.server")

class CallAttempt(TypedDict, total=False):
    stage: str
    provider: str
    model: str
    status: str
    run_id: str
    started_at: str
    elapsed_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    response_id: str | None
    comparison_response_id: str | None
    comparison_elapsed_ms: int | None
    cache_diagnostics: dict[str, Any] | None


class CallUsage:
    def __init__(self, writer: Documents, provider: ChatModelProvider, model: str, stage: str):
        self.writer = writer
        usage = _load_usage(writer)
        attempt: CallAttempt = {
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
                         and item.get("provider") == attempt["provider"]
                         and item.get("model") == attempt["model"]
                         and item.get("stage") == attempt["stage"]
                         and safe_response_id(item.get("response_id"))), None)
        # 현재 어댑터에서 진단 옵션을 지원하는 호출만 비교한다.
        if attempt["provider"] != "openai" or not re.match(r"^gpt-6(?:[.-]|$)", model.strip(), re.IGNORECASE):
            baseline = None
        baseline_time = _utc_time(baseline.get("started_at")) if baseline else None
        attempt.update({
            "started_at": now.isoformat(), "response_id": None,
            "comparison_response_id": baseline["response_id"] if baseline else None,
            "comparison_elapsed_ms": max(0, round((now - baseline_time).total_seconds() * 1000)) if baseline_time else None,
            "cache_diagnostics": None,
        })
        attempts.append(attempt)
        _record_usage(writer, usage)
        LOGGER.info(
            "provider call stage=%s provider=%s model=%s status=attempt "
            "elapsed_ms=unknown input_tokens=unknown output_tokens=unknown cached_tokens=unknown",
            attempt["stage"],
            attempt["provider"],
            attempt["model"],
        )

        self.usage = usage
        self.attempt = attempt
        self.started = perf_counter()

    def record_failed_completion(self, result: CompletionResult) -> None:
        self.attempt.update({
            "input_tokens": _count(result.input_tokens),
            "output_tokens": _count(result.output_tokens),
            "cached_tokens": _count(result.cached_tokens),
        })

    def failed(self) -> None:
        self.attempt.update({"status": "failed", "elapsed_ms": _elapsed_ms(self.started)})
        _record_usage(self.writer, self.usage)
        LOGGER.info(
            "provider call stage=%s provider=%s model=%s status=failed "
            "elapsed_ms=%s input_tokens=unknown output_tokens=unknown cached_tokens=unknown",
            self.attempt["stage"],
            self.attempt["provider"],
            self.attempt["model"],
            self.attempt["elapsed_ms"],
        )

    def succeeded(self, result: CompletionResult) -> None:
        self.attempt.update({
            "status": "success", "elapsed_ms": _elapsed_ms(self.started),
            "input_tokens": _count(result.input_tokens), "output_tokens": _count(result.output_tokens),
            "cached_tokens": _count(result.cached_tokens), "response_id": safe_response_id(result.response_id),
            "cache_diagnostics": safe_diagnostics(result.cache_diagnostics),
        })
        _record_usage(self.writer, self.usage)
        LOGGER.info(
            "provider call stage=%s provider=%s model=%s status=success "
            "elapsed_ms=%s input_tokens=%s output_tokens=%s cached_tokens=%s",
            self.attempt["stage"],
            self.attempt["provider"],
            self.attempt["model"],
            self.attempt["elapsed_ms"],
            _logged_count(self.attempt["input_tokens"]),
            _logged_count(self.attempt["output_tokens"]),
            _logged_count(self.attempt["cached_tokens"]),
        )
        diagnostic = self.attempt["cache_diagnostics"] or {}
        LOGGER.info(
            "provider cache stage=%s model=%s type=%s reason=%s cached_tokens=%s",
            self.attempt["stage"], self.attempt["model"], diagnostic.get("type", "unknown"),
            diagnostic.get("reason", "unknown"), _logged_count(self.attempt["cached_tokens"]),
        )

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
