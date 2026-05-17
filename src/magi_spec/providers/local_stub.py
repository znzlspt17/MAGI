"""Future local/self-hosted provider stub.

MAGI v1 does not support live local model execution. This stub exists only as
an adapter extension point and does not require credentials.
"""

from __future__ import annotations

from magi_spec.core.errors import MagiError
from magi_spec.providers.base import LLMProvider


class LocalStubProvider(LLMProvider):
    provider_name = "local"

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        del messages, model, temperature
        raise MagiError("Local model provider is a future extension stub for MAGI v1.")
