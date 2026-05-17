"""Future self-hosted provider stub."""

from __future__ import annotations

from magi_spec.core.errors import MagiError
from magi_spec.providers.base import LLMProvider


class SelfHostedStubProvider(LLMProvider):
    provider_name = "self_hosted"

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        del messages, model, temperature
        raise MagiError("Self-hosted provider is a future extension stub for MAGI v1.")
