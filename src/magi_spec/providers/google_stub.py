"""Future Google Gemini provider stub."""

from __future__ import annotations

from magi_spec.core.errors import MagiError
from magi_spec.providers.base import LLMProvider


class GoogleStubProvider(LLMProvider):
    provider_name = "google"

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        del messages, model, temperature
        raise MagiError("Google provider is a future extension stub for MAGI v1.")
