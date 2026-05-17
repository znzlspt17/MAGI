"""Provider adapter abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    provider_name: str

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        """Return a model completion for the provided chat-style messages."""


class ProviderFactory:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.provider_name] = provider

    def get(self, provider_name: str) -> LLMProvider:
        try:
            return self._providers[provider_name]
        except KeyError as exc:
            available = ", ".join(sorted(self._providers))
            raise ValueError(f"Unknown provider '{provider_name}'. Available: {available}") from exc
