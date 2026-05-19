from __future__ import annotations

import pytest

from magi_spec.core.agent_context import (
    build_agent_visible_context,
    context_contains_routing_metadata,
)
from magi_spec.core.errors import MagiError
from magi_spec.core.prompts import load_prompt


def test_agent_visible_context_redacts_routing_metadata() -> None:
    state = {
        "run_id": "magi_test",
        "status": "REVIEWING",
        "user_request": "Build package.",
        "project_manifest_path": "/tmp/manifest.json",
        "web_sources_path": "/tmp/web_sources.json",
        "evidence_registry_path": "/tmp/evidence.json",
        "intent_parse": "intent",
        "requirement_lock": "lock",
        "scope_classification": "scope",
        "assumptions": ["a"],
        "blocking_questions": ["b"],
        "section_status": {"mission": "PASS"},
        "model_routing": {"melchior": {"provider": "openai", "model": "gpt-4.1-mini"}},
        "private_model_assignments": {"melchior": {"provider": "openai", "model": "gpt-4.1-mini"}},
    }

    context = build_agent_visible_context(state, agent_id="melchior", round_number=1)

    assert "private_model_assignments" not in context
    assert "model_routing" not in context
    assert "openai" not in context.lower()
    assert "gpt-4.1-mini" not in context.lower()
    assert context_contains_routing_metadata(context) is False


def test_prompt_loader_reads_existing_prompt() -> None:
    prompt = load_prompt("melchior")
    assert "architecture reviewer" in prompt.lower()


def test_prompt_loader_rejects_invalid_id() -> None:
    with pytest.raises(MagiError):
        load_prompt("../secret")


def test_peer_output_content_is_redacted_for_routing_identity() -> None:
    state = {
        "run_id": "magi_test",
        "status": "REVIEWING",
        "user_request": "Build package.",
        "melchior_outputs": [{"status": "PASS", "content": "Use OpenAI gpt-4.1-mini result"}],
        "balthasar_outputs": [{"status": "PASS", "content": "Provider: anthropic"}],
        "casper_outputs": [{"status": "PASS", "content": "No issue"}],
        "section_status": {"mission": "PASS"},
    }

    context = build_agent_visible_context(state, agent_id="casper", round_number=1)

    assert "openai" not in context.lower()
    assert "gpt-4.1-mini" not in context.lower()
    assert "anthropic" not in context.lower()
