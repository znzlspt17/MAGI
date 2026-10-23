"""공식 HTTP 응답 hook으로 통합이 생략하는 정산 수치만 관측한다.

https://pydantic.dev/docs/httpx2/advanced/event-hooks/
https://developers.openai.com/api/docs/guides/prompt-caching
응답 본문·인증 헤더·생성 문장은 저장하거나 로깅하지 않는다.
"""

from backend.infrastructure.cache_diagnostics import safe_diagnostics, safe_response_id


def count(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


class UsageObservation:
    def __init__(self):
        self.values = None

    def __call__(self, response):
        if response.status_code != 200:
            return
        response.read()
        try:
            data = response.json()
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        details = usage.get("input_tokens_details")
        details = details if isinstance(details, dict) else {}
        writes = details.get("cache_write_tokens_details")
        writes = writes if isinstance(writes, dict) else {}
        self.values = {
            "input_tokens": count(usage.get("input_tokens")),
            "output_tokens": count(usage.get("output_tokens")),
            "cached_tokens": count(details.get("cached_tokens")),
            "cache_write_tokens": count(details.get("cache_write_tokens")),
            "cache_write_30m_tokens": count(writes.get("ttl_30m_tokens")),
            "cache_write_12h_tokens": count(writes.get("ttl_12h_tokens")),
            "response_id": safe_response_id(data.get("id")),
            "cache_diagnostics": safe_diagnostics(data.get("prompt_cache_diagnostics")),
        }
