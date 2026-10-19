"""캐시 진단에서 허용한 메타데이터만 보존한다."""

import re
from typing import Any


_TYPES = {"cache_hit", "cache_miss", "comparison_response_not_found", "unavailable"}
_REASONS = {
    "model_changed", "prompt_cache_key_changed", "service_tier_changed",
    "tools_changed", "text_format_changed", "reasoning_effort_changed",
    "verbosity_changed", "context_compacted", "input_changed",
}


def safe_response_id(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"resp_[A-Za-z0-9_-]{1,123}", value):
        return value
    return None


def safe_diagnostics(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return {"type": "unknown", "reason": "unknown"}
    kind, reason = value.get("type"), value.get("reason")
    result = {
        "type": kind if isinstance(kind, str) and kind in _TYPES else "unknown",
        "reason": reason if isinstance(reason, str) and reason in _REASONS else "unknown",
    }
    for field in ("comparison_reusable_tokens", "cache_missed_tokens"):
        count = value.get(field)
        result[field] = count if type(count) is int and count >= 0 else None
    return result
