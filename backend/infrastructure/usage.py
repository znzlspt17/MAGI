"""안전하게 공개할 수 있는 제공자 사용량 요약."""

from __future__ import annotations

from typing import Any


def provider_usage_summary(value: Any) -> dict[str, Any] | None:
    """기록된 호출 목록에서 토큰 합계와 알려진 범위를 계산한다."""
    if not isinstance(value, dict):
        return None
    attempts = value.get("attempts")
    if not isinstance(attempts, list):
        return None

    calls = len(attempts)
    successful = [item for item in attempts if _status(item) == "success"]
    failed = sum(1 for item in attempts if _status(item) == "failed")
    input_values = _token_values(successful, "input_tokens")
    output_values = _token_values(successful, "output_tokens")
    openai_successful = [item for item in successful if _provider(item) == "openai"]
    cached_values = _token_values(openai_successful, "cached_tokens")
    cache_pairs = [
        item
        for item in openai_successful
        if _token(item, "input_tokens") is not None
        and _token(item, "cached_tokens") is not None
        and (_token(item, "cached_tokens") or 0) <= (_token(item, "input_tokens") or 0)
    ]
    pair_input = sum(_token(item, "input_tokens") or 0 for item in cache_pairs)
    pair_cached = sum(_token(item, "cached_tokens") or 0 for item in cache_pairs)

    return {
        "recording_incomplete": value.get("recording_incomplete") is True,
        "calls": calls,
        "successful_calls": len(successful),
        "failed_calls": failed,
        "input_tokens": sum(input_values) if input_values else None,
        "output_tokens": sum(output_values) if output_values else None,
        "cached_tokens": sum(cached_values) if cached_values else None,
        "input_token_coverage": {
            "known_calls": len(input_values),
            "successful_calls": len(successful),
        },
        "output_token_coverage": {
            "known_calls": len(output_values),
            "successful_calls": len(successful),
        },
        "cache_rate": {
            "value": pair_cached / pair_input if pair_input else None,
            "known_calls": len(cache_pairs),
            "successful_calls": len(openai_successful),
            "known_input_tokens": pair_input if cache_pairs else None,
        },
    }


def _status(value: Any) -> str:
    return value.get("status", "") if isinstance(value, dict) else ""


def _provider(value: Any) -> str:
    return value.get("provider", "") if isinstance(value, dict) else ""


def _token_values(attempts: list[dict[str, Any]], field: str) -> list[int]:
    return [token for item in attempts if (token := _token(item, field)) is not None]


def _token(value: Any, field: str) -> int | None:
    if not isinstance(value, dict):
        return None
    token = value.get(field)
    return token if type(token) is int and token >= 0 else None
