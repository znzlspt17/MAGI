"""Deterministic provider used only by tests."""

from __future__ import annotations

from magi_spec.providers.base import LLMProvider


class MockProvider(LLMProvider):
    provider_name = "mock"

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        del model, temperature
        last = messages[-1]["content"] if messages else ""
        return f"MOCK_PROVIDER_RESPONSE\n{last[:1200]}"
