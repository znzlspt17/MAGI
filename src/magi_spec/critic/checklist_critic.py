"""Checklist Critic for v2 pipeline."""

from __future__ import annotations

from typing import Any

from magi_spec.core.provider_output import extract_json_object
from magi_spec.critic.checklist import run_deterministic_checks
from magi_spec.schemas.issue_packet import (
    IssuePacket,
    merge_issue_lists,
    parse_issue_list,
)
from magi_spec.schemas.requirement_lock import RequirementLockSheet


class ChecklistCritic:
    """Runs deterministic + LLM-assisted checklist review on the draft spec.

    Agent ID uses the 'critic' routing key in v2 pipeline config.
    """

    agent_id = "critic"

    def critique(
        self,
        spec_md: str,
        sheet: RequirementLockSheet,
        *,
        provider_complete_fn: Any,  # callable(prompt: str) -> str
    ) -> list[IssuePacket]:
        # 1. Deterministic checks (always authoritative, no LLM needed)
        deterministic = run_deterministic_checks(spec_md, sheet)

        # 2. LLM-assisted check (adds non-overlapping issues)
        try:
            raw = provider_complete_fn(_build_prompt(spec_md, sheet))
            parsed = extract_json_object(raw)
            llm_issues = parse_issue_list(parsed)
        except Exception:
            llm_issues = []

        # 3. Merge (deterministic wins on checklist_id collision)
        return merge_issue_lists(deterministic, llm_issues)


def _build_prompt(spec_md: str, sheet: RequirementLockSheet) -> str:
    mandatory_text = "\n".join(
        f"- [{r.id}] {r.text}" for r in sheet.mandatory_requirements
    ) or "- (none specified)"
    unresolved = "\n".join(f"- {q}" for q in sheet.unresolved_questions) or "- (none)"

    return (
        f"You are a checklist critic reviewing an AI coding agent specification.\n\n"
        f"Mandatory requirements from lock sheet:\n{mandatory_text}\n\n"
        f"Unresolved questions:\n{unresolved}\n\n"
        f"Draft specification (truncated to 6000 chars):\n{spec_md[:6000]}\n\n"
        f"Check the spec against these criteria and report violations as a JSON list:\n"
        f"- All 26 required headings present\n"
        f"- Out of Scope (### 4.2) not empty\n"
        f"- Forbidden Behaviors (## 10) not empty\n"
        f"- Acceptance Criteria (## 20) has verifiable conditions\n"
        f"- Test Plan (## 21) not empty\n"
        f"- No ambiguous terms (robust, good, appropriate) in Mandatory Requirements\n"
        f"- Each mandatory requirement from lock sheet appears in the spec\n\n"
        f"Return JSON: {{\"issues\": [{{\"issue_id\": \"...\", \"section\": \"...\", "
        f"\"severity\": \"blocking|major|minor\", \"checklist_id\": \"...\", "
        f"\"problem\": \"...\", \"required_change\": \"...\"}}]}}\n"
        f"If there are no issues, return {{\"issues\": []}}\n"
        f"Return ONLY valid JSON."
    )
