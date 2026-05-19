from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from magi_spec.core.errors import MagiError, MissingCredentialError
from magi_spec.providers.openai_adapter import OpenAIProvider


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


def test_openai_adapter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider(api_key=None)
    with pytest.raises(MissingCredentialError):
        provider.complete([{"role": "user", "content": "hi"}], model="gpt-5.4-nano")


def test_openai_adapter_prefers_output_text(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIProvider(api_key="test")

    def fake_urlopen(request: urllib.request.Request, timeout: int = 120):  # noqa: ARG001
        assert request.full_url.endswith("/v1/responses")
        return _FakeHTTPResponse({"output_text": "hello"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    text = provider.complete([{"role": "user", "content": "hi"}], model="gpt-5.4-nano")
    assert text == "hello"


def test_openai_adapter_parses_output_items(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIProvider(api_key="test")
    payload = {
        "output": [
            {"content": [{"type": "output_text", "text": "line1"}]},
            {"content": [{"type": "text", "text": "line2"}]},
        ]
    }

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=120: _FakeHTTPResponse(payload),  # noqa: ARG005
    )
    text = provider.complete([{"role": "user", "content": "hi"}], model="gpt-5.4-nano")
    assert text == "line1\nline2"


def test_openai_adapter_http_error_raises_magi_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIProvider(api_key="test")
    http_error = urllib.error.HTTPError(
        url="https://api.openai.com/v1/responses",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b'{"error":{"message":"bad key"}}'),
    )

    def raise_http_error(request: urllib.request.Request, timeout: int = 120):  # noqa: ARG001
        raise http_error

    monkeypatch.setattr(urllib.request, "urlopen", raise_http_error)
    with pytest.raises(MagiError, match="HTTP 401"):
        provider.complete([{"role": "user", "content": "hi"}], model="gpt-5.4-nano")
