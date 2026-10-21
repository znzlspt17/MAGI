"""Checklist Critic for v2 pipeline."""

from __future__ import annotations

import json
import re
from typing import Any
from backend.errors import ReviewValidationError
from backend.infrastructure.output_language import has_hangul, prose

from backend.infrastructure.provider_output import extract_json_object
from backend.models import ReviewResponse
from backend.infrastructure.prompt_messages import complete as complete_messages
from backend.infrastructure.prompt_messages import flatten
from backend.infrastructure.prompt_messages import messages as build_messages
from backend.infrastructure.prompts import load_prompt
from backend.models import (
    IssuePacket,
    merge_issue_lists,
    parse_issue_list,
)
from backend.models import RequirementLockSheet
from backend.services.checklist import run_deterministic_checks


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
        provider_complete_fn: Any | None = None,
        provider_messages_fn: Any | None = None,
        user_request: str = "",
        previous_issues: list[IssuePacket] | list[dict[str, Any]] | None = None,
        revision_feedback: str = "",
        revision_history: list[str] | None = None,
    ) -> list[IssuePacket]:
        sheet.require_validated()
        # 1. Deterministic checks (always authoritative, no LLM needed)
        deterministic = run_deterministic_checks(spec_md, sheet)

        # 2. LLM-assisted check (adds non-overlapping issues)
        payload = _build_messages(
            spec_md,
            sheet,
            user_request=user_request,
            previous_issues=previous_issues,
            revision_feedback=revision_feedback,
            revision_history=revision_history or [],
        )
        raw = complete_messages(
            payload,
            provider_complete_fn=provider_complete_fn,
            provider_messages_fn=provider_messages_fn,
        )
        try:
            if isinstance(raw, ReviewResponse):
                parsed = raw.model_dump()
                for index, item in enumerate(parsed["issues"], start=1):
                    item["issue_id"] = f"LLM-ISSUE-{index:03d}"
            else:
                parsed = extract_json_object(raw)
            llm_issues = _parse_provider_issues(
                parsed,
                {
                    item.id
                    for items in (
                        sheet.mandatory_requirements,
                        sheet.recommended_requirements,
                        sheet.optional_requirements,
                        sheet.non_scope,
                        sheet.constraints,
                    )
                    for item in items
                    if item.id
                },
            )
        except (AttributeError, TypeError):
            raise ReviewValidationError() from None

        # 3. Merge (deterministic wins on checklist_id collision)
        return merge_issue_lists(deterministic, llm_issues)


def _build_messages(
    spec_md: str,
    sheet: RequirementLockSheet,
    *,
    user_request: str,
    previous_issues: list[IssuePacket] | list[dict[str, Any]] | None,
    revision_feedback: str,
    revision_history: list[str],
) -> list[dict[str, str]]:
    history = "\n\n".join(item for item in revision_history if item.strip())
    product_sheet = sheet.to_dict()
    workflow = product_sheet.pop("workflow_constraints")
    canonical = json.dumps(product_sheet, ensure_ascii=False, indent=2)
    return build_messages(
        load_prompt("checklist_critic"),
        user_request,
        canonical,
        ("Revision feedback history", history),
        ("Latest revision feedback", revision_feedback),
        ("Issues from the previous critic pass", _serialize_previous_issues(previous_issues)),
        ("Draft specification", spec_md),
        workflow_constraints=workflow,
    )


def _parse_provider_issues(
    parsed: dict[str, Any] | None,
    known_requirement_ids: set[str],
) -> list[IssuePacket]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("issues"), list):
        raise ReviewValidationError()
    raw_items = parsed["issues"]
    for item in raw_items:
        if (
            not isinstance(item, dict)
            or item.get("severity")
            not in {
                "blocking",
                "major",
                "minor",
            }
            or not all(
                isinstance(item.get(key), str) and item[key].strip()
                for key in (
                    "issue_id",
                    "section",
                    "checklist_id",
                    "problem",
                    "required_change",
                )
            )
        ):
            raise ReviewValidationError()
        if "requirement_id" not in item:
            raise ReviewValidationError(check="review_requirement")
        if item["requirement_id"] is not None:
            if (
                not isinstance(item["requirement_id"], str)
                or not item["requirement_id"].strip()
                or item["requirement_id"] not in known_requirement_ids
            ):
                raise ReviewValidationError(check="review_requirement")
        if "evidence" not in item:
            raise ReviewValidationError(check="review_evidence")
        evidence = item["evidence"]
        if not isinstance(evidence, list) or not evidence or any(
                not isinstance(entry, dict)
                or not isinstance(entry.get("source"), str)
                or not entry["source"].strip()
                or not isinstance(entry.get("quote"), str)
                or not entry["quote"].strip()
            for entry in evidence
        ):
            raise ReviewValidationError(check="review_evidence")
        if item.get("defect_kind") not in {"requirements_gap", "spec_omission", "verification_gap", "confirmed_conflict"} or not all(
            isinstance(item.get(key), str) for key in ("resolution_reason", "missing_information", "decision_key")) or not item["resolution_reason"].strip() or not item["decision_key"].strip():
            raise ReviewValidationError(["Supply defect_kind, resolution_reason, missing_information and a stable decision_key."], check="review_classification")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,100}", item["decision_key"]):
            raise ReviewValidationError(["decision_key must be a stable English topic key."], check="decision_key")
        kind = item.get("resolution_kind", "auto_fix")
        question = item.get("decision_question")
        if kind not in {"auto_fix", "user_decision"}:
            raise ReviewValidationError(["issues.resolution_kind must be auto_fix or user_decision."], check="review_classification")
        if kind == "user_decision" and (not isinstance(question, str) or not question.strip() or not has_hangul(prose(question))):
            raise ReviewValidationError(["issues.decision_question must be a non-empty Korean question for user_decision."], check="question_text")
        if kind == "auto_fix" and question is not None:
            raise ReviewValidationError(["issues.decision_question must be null for auto_fix."], check="resolution_auto_fix")
    issues = parse_issue_list(parsed)
    if len(issues) != len(raw_items):
        raise ReviewValidationError()
    for issue in issues:
        issue.status = "open"
    return issues


def _build_prompt(
    spec_md: str,
    sheet: RequirementLockSheet,
    *,
    user_request: str = "",
    previous_issues: list[IssuePacket] | list[dict[str, Any]] | None = None,
    revision_feedback: str = "",
) -> str:
    """기존 문자열 콜백 검증용 호환 진입점이다."""
    return flatten(
        _build_messages(
            spec_md,
            sheet,
            user_request=user_request,
            previous_issues=previous_issues,
            revision_feedback=revision_feedback,
            revision_history=[revision_feedback] if revision_feedback else [],
        )
    )

def _serialize_previous_issues(
    previous_issues: list[IssuePacket] | list[dict[str, Any]] | None,
) -> str:
    if not previous_issues:
        return "[]"
    serialized = [
        issue.to_dict() if isinstance(issue, IssuePacket) else issue
        for issue in previous_issues
        if isinstance(issue, (IssuePacket, dict))
    ]
    return json.dumps(serialized, ensure_ascii=False, indent=2)
