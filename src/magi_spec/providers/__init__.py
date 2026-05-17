"""Provider adapter registry."""

from magi_spec.providers.anthropic_stub import AnthropicStubProvider
from magi_spec.providers.base import ProviderFactory
from magi_spec.providers.google_stub import GoogleStubProvider
from magi_spec.providers.local_stub import LocalStubProvider
from magi_spec.providers.mock_provider import MockProvider
from magi_spec.providers.openai_adapter import OpenAIProvider
from magi_spec.providers.self_hosted_stub import SelfHostedStubProvider


def default_provider_factory() -> ProviderFactory:
    factory = ProviderFactory()
    factory.register(OpenAIProvider())
    factory.register(MockProvider())
    factory.register(AnthropicStubProvider())
    factory.register(GoogleStubProvider())
    factory.register(LocalStubProvider())
    factory.register(SelfHostedStubProvider())
    return factory


__all__ = [
    "AnthropicStubProvider",
    "GoogleStubProvider",
    "LocalStubProvider",
    "MockProvider",
    "OpenAIProvider",
    "SelfHostedStubProvider",
    "ProviderFactory",
    "default_provider_factory",
]
