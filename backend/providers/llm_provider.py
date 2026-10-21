"""OpenAI Responses API 단일 제공자."""

from __future__ import annotations

import os
import re
from openai import OpenAI, OpenAIError, APIStatusError
from pydantic import BaseModel, ValidationError
from typing import Any

from backend.infrastructure.cache_diagnostics import safe_response_id, safe_diagnostics
from backend.errors import Error, MissingCredentialError, ConversationUnavailableError
from backend.models import CompletionResult
from backend.model_policy import require_model, MAX_OUTPUT_TOKENS, SERVICE_TIER


_REASONING_MODEL_FAMILY = re.compile(r"^gpt-(?:5|6)(?:[.-]|$)", re.IGNORECASE)
_GPT6_MODEL_FAMILY = re.compile(r"^gpt-6(?:[.-]|$)", re.IGNORECASE)


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def validate_credentials(self) -> None:
        self._require_key()

    def _require_key(self) -> str:
        key = (
            self.api_key
            if self.api_key is not None
            else os.environ.get("OPENAI_API_KEY")
        )
        if not key:
            raise MissingCredentialError(
                "OpenAI provider selected but OPENAI_API_KEY is not set. "
                "Set OPENAI_API_KEY for MAGI runtime."
            )
        return key

    def create_conversation(self) -> str:
        from backend.access.context import METER
        meter=METER.get()
        if meter is not None:
            meter.access.check_execution(meter.uid,meter.jid,meter.generation)
        try:
            with OpenAI(api_key=self._require_key(), timeout=120, max_retries=0) as client:
                identifier = client.conversations.create().id
        except OpenAIError:
            raise Error("OpenAI conversation creation failed.") from None
        from backend.infrastructure.conversation_state import valid_conversation_id
        if not valid_conversation_id(identifier):
            raise Error("OpenAI conversation ID is invalid.")
        return identifier

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        instructions: str | None = None,
        conversation_id: str | None = None,
        text_format: type[BaseModel] | None = None,
    ) -> str:
        return self.complete_result(
            messages,
            model=model,
            temperature=temperature, instructions=instructions,
            conversation_id=conversation_id, text_format=text_format,
        ).text

    def complete_result(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        cache_key: str | None = None,
        comparison_response_id: str | None = None,
        conversation_id: str | None = None,
        instructions: str | None = None,
        text_format: type[BaseModel] | None = None,
    ) -> CompletionResult:
        require_model(model)
        api_key = self._require_key()
        if instructions is None:
            instructions = "\n\n".join(item.get("content", "") for item in messages
                                           if item.get("role") == "system")
        messages = [item for item in messages if item.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": model,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "service_tier": SERVICE_TIER,
            "input": [
                {
                    "role": message.get("role", "user"),
                    "content": message.get("content", ""),
                }
                for message in messages
            ],
        }
        if instructions:
            payload["instructions"] = instructions
        if conversation_id:
            payload["conversation"] = conversation_id
        payload["store"] = True
        from backend.access.context import METER
        meter = METER.get()
        if meter is not None:
            payload['max_output_tokens'] = meter.price(model)[3]
            payload['truncation'] = 'disabled'
        # GPT-5·GPT-6 계열은 추론 설정과 충돌하지 않도록 temperature를 생략한다.
        if temperature is not None and not _is_reasoning_model(model):
            payload["temperature"] = temperature
        if _is_gpt6_model(model):
            # 자동 경계 하나와 명시적 경계 최대 세 개를 함께 유지한다.
            # 공통 developer 규칙과 원본 요청·기준 문맥에 재사용 경계를 둔다.
            remaining = 3
            for message in payload["input"]:
                content = message.get("content")
                if remaining and message.get("role") == "developer" and isinstance(content, str):
                    message["content"] = [_cacheable_text(content)]
                    remaining -= 1
                elif (remaining and message.get("role") == "user"
                        and isinstance(content, str)
                        and content.startswith(("Original user request (immutable):\n", "Canonical context:\n"))):
                    message["content"] = [_cacheable_text(content)]
                    remaining -= 1
            payload["prompt_cache_options"] = {"mode": "implicit", "ttl": "30m"}
            comparison_id = safe_response_id(comparison_response_id)
            if comparison_id:
                payload["prompt_cache_options"]["comparison_response_id"] = comparison_id
            if cache_key:
                payload["prompt_cache_key"] = cache_key

        reservation = meter.reserve(model) if meter is not None else None
        try:
            with OpenAI(api_key=api_key, timeout=300, max_retries=0) as client:
                if text_format is None:
                    response = client.responses.create(**payload)
                else:
                    response = client.responses.parse(**payload, text_format=text_format)
        except APIStatusError as exc:
            if meter is not None:
                meter.settle(reservation,model,None)
            if conversation_id and exc.status_code == 404 and exc.param == "conversation":
                raise ConversationUnavailableError("OpenAI conversation is unavailable.") from None
            raise Error("OpenAI request failed.") from None
        except (OpenAIError, ValidationError, ValueError):
            if meter is not None:
                meter.settle(reservation,model,None)
            # SDK 예외에는 요청과 응답 원문이 포함될 수 있어 전파하지 않는다.
            raise Error("OpenAI request failed.") from None
        data = response.model_dump()
        text = response.output_text
        parsed = None
        failure = None
        if response.status != "completed":
            failure = "OpenAI response did not complete."
        elif not isinstance(text, str) or not text.strip():
            failure = "OpenAI returned no text response."
        else:
            parsed = response.output_parsed if text_format is not None else None
            if text_format is not None and not isinstance(parsed, text_format):
                failure = "OpenAI returned no structured response."
        if failure:
            if meter is not None:
                # 실패 응답에도 관측된 사용량은 보존하되 비용은 미확정으로 남긴다.
                meter.record_usage(reservation,model,_usage_count(data,"input_tokens"),
                                   _usage_count(data,"output_tokens"),_cached_tokens(data))
                meter.settle(reservation,model,None)
            raise Error(failure)

        result = CompletionResult(
            text=text.strip(),
            parsed=parsed,
            input_tokens=_usage_count(data, "input_tokens"),
            output_tokens=_usage_count(data, "output_tokens"),
            cached_tokens=_cached_tokens(data),
            response_id=safe_response_id(data.get("id")),
            cache_diagnostics=safe_diagnostics(data.get("prompt_cache_diagnostics")),
        )
        if meter is not None:
            meter.settle(reservation,model,result)
        return result



def _cacheable_text(text: str) -> dict[str, Any]:
    """본문은 바꾸지 않고 재사용할 앞부분의 끝만 지정한다."""
    return {
        "type": "input_text", "text": text,
        "prompt_cache_breakpoint": {"mode": "explicit"},
    }


def _usage_count(data: dict[str, Any], field: str) -> int | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    value = usage.get(field)
    return value if type(value) is int and value >= 0 else None


def _cached_tokens(data: dict[str, Any]) -> int | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details")
    if not isinstance(details, dict):
        return None
    value = details.get("cached_tokens")
    return value if type(value) is int and value >= 0 else None


def _is_reasoning_model(model: str) -> bool:
    """GPT-5·GPT-6의 명시적 버전·변형 접두사만 추론 모델로 취급한다."""
    return bool(_REASONING_MODEL_FAMILY.match(model.strip()))


def _is_gpt6_model(model: str) -> bool:
    """GPT-6 Responses 요청에만 공식 prompt-cache 옵션을 추가한다."""
    return bool(_GPT6_MODEL_FAMILY.match(model.strip()))
