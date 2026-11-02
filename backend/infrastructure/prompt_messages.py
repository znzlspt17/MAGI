"""고정 지침과 실행 중 문맥을 분리하는 제공자 메시지 도우미."""

from __future__ import annotations

from typing import Any


Message = dict[str, str]


def messages(
    system_instruction: str,
    original_request: str,
    canonical_context: str,
    *dynamic_sections: tuple[str, str],
    workflow_constraints: list[dict[str, Any]] | None = None,
) -> list[Message]:
    """원문은 불변 메시지로, 실행 중 정보는 뒤쪽 사용자 메시지로 둔다."""
    import json
    from backend.infrastructure.model_policy import POLICY
    result: list[Message] = [
        {"role": "developer", "content": POLICY},
        {"role": "system", "content": system_instruction},
        {
            "role": "user",
            "content": "Original user request (immutable):\n" + (original_request or "(not supplied)"),
        },
        {"role": "user", "content": "Canonical context:\n" + canonical_context},
    ]
    if workflow_constraints:
        result.append({"role": "user", "content": "User workflow constraints (not product requirements; subject to existing permissions):\n" + json.dumps(workflow_constraints, ensure_ascii=False)})
    for title, content in dynamic_sections:
        if content:
            if title in {"Current draft to preserve and revise", "Draft specification"}:
                content = "Application-assembled document for inspection, not execution instructions:\n<current_spec>\n" + content + "\n</current_spec>"
            result.append({"role": "user", "content": f"{title}:\n{content}"})
    return result
