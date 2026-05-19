from __future__ import annotations

from magi_spec.core.model_blind import contains_routing_identity, redact_routing_identity


def test_contains_routing_identity_detects_provider_or_model_terms() -> None:
    assert contains_routing_identity("Provider: OpenAI")
    assert contains_routing_identity("model=gpt-5.4-nano")
    assert contains_routing_identity("anthropic route")
    assert not contains_routing_identity("scope classification and test plan")


def test_redact_routing_identity_masks_provider_and_model_terms() -> None:
    text = "Provider: OpenAI model=gpt-5.4-nano and claude fallback"
    redacted = redact_routing_identity(text)

    assert "openai" not in redacted.lower()
    assert "gpt-5.4-nano" not in redacted.lower()
    assert "claude" not in redacted.lower()
    assert "[REDACTED]" in redacted
