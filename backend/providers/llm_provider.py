"""공식 LangChain chat model 인터페이스와 MAGI 비용 경계."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
import httpx2

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from backend.errors import Error, MissingCredentialError
from backend.infrastructure.cache_diagnostics import safe_response_id, safe_diagnostics
from backend.models import CompletionResult
from backend.model_policy import require_model, MAX_OUTPUT_TOKENS, SERVICE_TIER
from backend.infrastructure.model_usage import UsageObservation


class ChatModelProvider:
    provider_name = "openai"

    def __init__(self, api_key: str | None = None, *, meter=None) -> None:
        self.api_key, self.meter = api_key, meter

    def validate_credentials(self) -> None:
        # 키의 해석과 접속은 공식 통합이 담당한다. 검증 중 외부 호출은 하지 않는다.
        import os
        if not self.api_key and not os.environ.get("OPENAI_API_KEY"):
            raise MissingCredentialError("OPENAI_API_KEY is not set for MAGI runtime.")


    def complete_result(
        self, messages: list[dict], *, model: str,
        temperature: float | None = None, instructions: str | None = None,
        text_format: type[BaseModel] | None = None,
        cache_key: str | None = None,
    ) -> CompletionResult:
        require_model(model)
        meter = self.meter
        options: dict[str, Any] = {
            "model_provider": "openai", "use_responses_api": True,
            "use_previous_response_id": False, "max_retries": 0,
            "timeout": 300, "max_tokens": MAX_OUTPUT_TOKENS,
            "service_tier": SERVICE_TIER, "truncation": "disabled",
        }
        if self.api_key is not None:
            options["api_key"] = self.api_key
        if temperature is not None and not re.match(r"^gpt-(?:5|6)(?:[.-]|$)", model, re.I):
            options["temperature"] = temperature
        if cache_key:
            options["model_kwargs"] = {"prompt_cache_key": cache_key}
        inputs = list(messages)
        if instructions is not None:
            inputs = [{"role": "system", "content": instructions},
                      *(item for item in inputs if item.get("role") != "system")]
        reservation = meter.reserve(model) if meter else None
        result = None
        observation = UsageObservation()
        client = None
        try:
            client = httpx2.Client(timeout=300, event_hooks={"response": [observation]})
            options["http_client"] = client
            llm = init_chat_model(model, **options)
            from backend.infrastructure.workflow_store import provider_entered
            if text_format is not None:
                structured = llm.with_structured_output(
                    text_format, method="json_schema", include_raw=True, strict=True,
                )
                provider_entered()
                packet = structured.invoke(inputs)
                raw, parsed = packet["raw"], packet["parsed"]
                parsing_error = packet["parsing_error"]
            else:
                provider_entered()
                raw, parsed, parsing_error = llm.invoke(inputs), None, None
            if not isinstance(raw, AIMessage):
                raise Error("모델 응답 형식을 확인할 수 없습니다.")
            result = completion_result(raw, parsed)
            if observation.values is not None:
                result = replace(result, **observation.values)
            if (parsing_error is not None or (text_format is not None and not isinstance(parsed, text_format))
                    or raw.response_metadata.get("status") in {"failed", "incomplete", "cancelled"}
                    or raw.response_metadata.get("finish_reason") in {"length", "content_filter"}
                    or (text_format is None and not result.text)):
                raise Error("모델 응답이 거부되었거나 완전한 결과를 반환하지 않았습니다.")
        except Exception:
            if result is None and observation.values is not None:
                result = CompletionResult(text="", **observation.values)
            if meter:
                if result is not None:
                    meter.record_usage(reservation, model, result.input_tokens, result.output_tokens,
                                       result.cached_tokens, result.cache_write_tokens,
                                       result.cache_write_30m_tokens, result.cache_write_12h_tokens)
                meter.settle(reservation, model, None)
            # 통합 예외에는 요청 본문이 포함될 수 있으므로 외부로 전달하지 않는다.
            error = Error("모델 호출을 완료하지 못했습니다.")
            error.completion = result
            raise error from None
        finally:
            if client is not None:
                client.close()
        if meter:
            meter.settle(reservation, model, result)
        return result


def completion_result(message: AIMessage, parsed=None) -> CompletionResult:
    """공식 표준 사용량을 우선하며 누락과 관측된 0을 구분한다."""
    usage = message.usage_metadata or {}
    details = usage.get("input_token_details") or {}
    metadata = message.response_metadata
    raw_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    raw_details = raw_usage.get("input_tokens_details") or {}
    writes = raw_details.get("cache_write_tokens_details") or {}
    return CompletionResult(
        text=message.text.strip(), parsed=parsed,
        input_tokens=_count(usage.get("input_tokens")),
        output_tokens=_count(usage.get("output_tokens")),
        cached_tokens=_count(details.get("cache_read")),
        response_id=safe_response_id(metadata.get("id") or message.id),
        cache_diagnostics=safe_diagnostics(metadata.get("prompt_cache_diagnostics")),
        cache_write_tokens=_count(details.get("cache_creation", raw_details.get("cache_write_tokens"))),
        cache_write_30m_tokens=_count(writes.get("ttl_30m_tokens")),
        cache_write_12h_tokens=_count(writes.get("ttl_12h_tokens")),
    )


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None
