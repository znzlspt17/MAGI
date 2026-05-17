"""OpenAI provider adapter.

The adapter validates credentials immediately and keeps provider details out of
agent-visible prompts. Network calls are isolated here so tests can swap in the
mock provider.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from magi_spec.core.errors import MagiError, MissingCredentialError
from magi_spec.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")

    def _require_key(self) -> str:
        if not self.api_key:
            raise MissingCredentialError(
                "OpenAI provider selected but OPENAI_API_KEY is not set. "
                "Set OPENAI_API_KEY for MAGI v1 runtime."
            )
        return self.api_key

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        api_key = self._require_key()
        payload: dict[str, Any] = {
            "model": model,
            "input": [
                {
                    "role": message.get("role", "user"),
                    "content": message.get("content", ""),
                }
                for message in messages
            ],
        }
        if temperature is not None:
            payload["temperature"] = temperature

        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise MagiError(f"OpenAI request failed with HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise MagiError(f"OpenAI request failed: {exc}") from exc

        if "output_text" in data:
            return str(data["output_text"])
        output = data.get("output", [])
        parts: list[str] = []
        for item in output:
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    parts.append(str(content.get("text", "")))
        return "\n".join(part for part in parts if part).strip()


OpenAIAdapter = OpenAIProvider
