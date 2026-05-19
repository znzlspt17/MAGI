"""Build model-blind context packets for MAGI agents."""

from __future__ import annotations

import json
from typing import Any

from magi_spec.core.model_blind import redact_routing_identity
from magi_spec.core.state import WorkflowState


PRIVATE_STATE_KEYS = {
    "private_model_assignments",
    "model_routing",
    "providers",
}

ROUTING_METADATA_WORDS = {
    "provider",
    "model",
    "version",
    "benchmark",
    "pricing",
    "context window",
}


def build_agent_visible_context(
    state: WorkflowState,
    *,
    agent_id: str,
    round_number: int,
) -> str:
    """Return a compact JSON context packet with private routing fields removed."""

    packet: dict[str, Any] = {
        "agent_role": agent_id,
        "round_number": round_number,
        "run_id": state.get("run_id", ""),
        "status": state.get("status", ""),
        "user_request": _truncate(state.get("user_request", ""), 6000),
        "input_source": state.get("input_source", ""),
        "project_manifest_path": state.get("project_manifest_path"),
        "web_sources_path": state.get("web_sources_path"),
        "evidence_registry_path": state.get("evidence_registry_path"),
        "intent_parse": _truncate(state.get("intent_parse", ""), 4000),
        "requirement_lock": _truncate(state.get("requirement_lock", ""), 4000),
        "scope_classification": _truncate(state.get("scope_classification", ""), 4000),
        "assumptions": state.get("assumptions", []),
        "blocking_questions": state.get("blocking_questions", []),
        "section_status": state.get("section_status", {}),
        "latest_peer_outputs": _latest_peer_outputs(state, agent_id),
        "conflict_summaries": _latest_items(state.get("conflict_reports", []), limit=3),
    }
    redacted = _redact(packet)
    return json.dumps(redacted, ensure_ascii=False, indent=2)


def context_contains_routing_metadata(context: str) -> bool:
    lowered = context.lower()
    return any(word in lowered for word in ROUTING_METADATA_WORDS)


def _latest_peer_outputs(state: WorkflowState, agent_id: str) -> list[dict[str, Any]]:
    keys = {
        "melchior": "melchior_outputs",
        "balthasar": "balthasar_outputs",
        "casper": "casper_outputs",
    }
    outputs: list[dict[str, Any]] = []
    for peer_id, key in keys.items():
        if peer_id == agent_id:
            continue
        items = state.get(key, [])
        if items:
            latest = dict(items[-1])
            latest.pop("evidence_ids", None)
            outputs.append(_redact(latest))
    return outputs


def _latest_items(items: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[-limit:]:
        if isinstance(item, dict):
            compact.append(_redact(dict(item)))
    return compact


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact(item)
            for key, item in value.items()
            if key not in PRIVATE_STATE_KEYS and not _is_routing_key(key)
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_routing_identity(value)
    return value


def _is_routing_key(key: str) -> bool:
    lowered = key.lower()
    return any(word.replace(" ", "_") in lowered for word in ROUTING_METADATA_WORDS)


def _truncate(text: Any, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"
