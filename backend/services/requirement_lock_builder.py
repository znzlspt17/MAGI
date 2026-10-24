"""Requirement Lock builder for v2 pipeline."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from backend.errors import RequirementNormalizationError
from backend.models import LockResponse
from backend.infrastructure.output_language import language_issues
from backend.infrastructure.stage_retry import attempt_limit, retry_messages
from backend.infrastructure.prompt_messages import messages as build_messages
from backend.infrastructure.prompts import load_prompt
from backend.models import InterviewResult
from backend.models import (
    AssumptionItem,
    QAItem,
    RequirementItem,
    RequirementLockSheet,
)


class RequirementLockBuilder:
    """검증 오류를 단계의 공통 예산 안에서 보정한다."""

    agent_id = "interviewer"

    def build(
        self,
        state: dict[str, Any],
        manifest: dict[str, Any],
        interview: InterviewResult,
        *,
        runtime=None,
        provider_messages_fn: Any,
    ) -> RequirementLockSheet:
        user_request = str(
            state.get("original_user_request") or state.get("user_request", "")
        )
        if state.get("requirement_lock_sheet") is not None:
            RequirementLockSheet.from_dict(state["requirement_lock_sheet"])
        payload = _build_messages(state, manifest, interview, user_request)
        original_payload = payload
        limit = attempt_limit()
        for attempt in range(limit):
            # 통신 오류는 검증 보정과 분리하고 그대로 전달한다.
            raw = provider_messages_fn(payload)
            try:
                if not isinstance(raw, LockResponse):
                    raise _response_validation_error(None)
                parsed = raw.model_dump()
                details = language_issues(raw)
                if details:
                    raise _normalization_error("language", details)
                if not _valid_lock_response(parsed):
                    raise _response_validation_error(parsed)
                sheet = _parse_sheet(parsed, interview=interview)
                from backend.services.workflow_constraints import validate_workflow, user_sources, validate_product_boundary
                try:
                    validate_workflow(sheet.workflow_constraints, user_sources(state))
                    validate_product_boundary(sheet)
                except ValueError as exc:
                    raise _normalization_error("workflow_constraints", [str(exc)]) from None
                _validate_preserved_mandatory_ids(state.get("requirement_lock_sheet"), sheet)
                # 인터뷰가 추론한 답은 실제 사용자 출처를 요구하는 보존 검사의 대상이 아니다.
                actual_sources = user_sources(state)
                _validate_decision_coverage(sheet, [answer for answer in interview.pre_answers
                    if "user_answer:" + answer.question_id in actual_sources], str(state.get("revision_feedback") or ""))
                from backend.knowledge.trace import validate_decisions
                retrieved = runtime.reusable_ids() if runtime else []
                previous = (state.get("requirement_lock_sheet") or {}).get("decisions", [])
                if runtime is not None:
                    sheet.decisions = runtime.bind_decisions(sheet.decisions, previous)
                    previous = runtime.bind_decisions(previous, previous)
                try:
                    validate_decisions(sheet.decisions, sheet.to_dict(), retrieved,
                                       str(state.get("revision_feedback") or ""), user_request,
                                       runtime.confirmed_sources(state) if runtime else None,
                                       previous, state.get("reused_decisions", []))
                except ValueError:
                    raise _normalization_error("trace", ["Decision trace references are invalid."]) from None
                from backend.services.project_decisions import validate_requirement_sources
                try:
                    validate_requirement_sources(sheet, state.get("reused_decisions", []), require_all=not bool(state.get("revision_feedback")))
                except ValueError as exc:
                    raise _normalization_error("trace", [str(exc)]) from None
                return sheet
            except RequirementNormalizationError as exc:
                logging.getLogger("backend.server").warning(
                    "requirement lock validation failed category=%s missing_count=%s attempt=%s",
                    exc.category, len(exc.validation_details), attempt + 1,
                )
                if attempt == limit - 1:
                    raise
                payload = retry_messages(original_payload, stage="requirement_lock", attempt=attempt + 1, error=exc)
        raise AssertionError("Unreachable normalization attempt.")


def _build_messages(
    state: dict[str, Any],
    manifest: dict[str, Any],
    interview: InterviewResult,
    user_request: str,
) -> list[dict[str, str]]:
    previous_sheet = dict(state["requirement_lock_sheet"]) if state.get("requirement_lock_sheet") else None
    workflow = previous_sheet.pop("workflow_constraints") if previous_sheet is not None else []
    canonical = {
        "project_manifest": manifest,
        "request_type": interview.request_type,
        "assumptions": interview.assumptions,
        "saved_answers": [item.to_dict() for item in interview.pre_answers],
        "unresolved_blocking_questions": interview.blocking_questions,
        "previous_lock_sheet": previous_sheet,
        "actual_user_sources": state.get("confirmed_user_sources", {}),
    }
    history = state.get("revision_history", [])
    history_text = "\n\n".join(
        str(item) for item in history if isinstance(item, str) and item.strip()
    )
    return build_messages(
        load_prompt("requirement_lock"),
        user_request,
        json.dumps(canonical, ensure_ascii=False, indent=2),
        ("Revision feedback history", history_text),
        ("Latest revision feedback", str(state.get("revision_feedback") or "")),
        workflow_constraints=workflow,
    )


def _parse_sheet(
    parsed: dict[str, Any] | None,
    *,
    interview: InterviewResult,
) -> RequirementLockSheet:
    if not isinstance(parsed, dict):
        raise RequirementNormalizationError("Requirement lock response is invalid.")

    def _req_list(key: str) -> list[RequirementItem]:
        return [RequirementItem.from_dict(item) for item in parsed[key]]

    mandatory = _req_list("mandatory_requirements")
    return RequirementLockSheet(
        lock_id=f"lock_{uuid4().hex[:8]}",
        request_type=interview.request_type,
        request_summary=parsed["request_summary"],
        user_answers=list(interview.pre_answers),
        mandatory_requirements=mandatory,
        recommended_requirements=_req_list("recommended_requirements"),
        optional_requirements=_req_list("optional_requirements"),
        non_scope=_req_list("non_scope"),
        assumptions=[AssumptionItem.from_dict(item) for item in parsed["assumptions"]],
        constraints=_req_list("constraints"),
        workflow_constraints=_req_list("workflow_constraints"),
        acceptance_criteria_seed=[item.strip() for item in parsed["acceptance_criteria_seed"] if item.strip()],
        unresolved_questions=[],
        source_refs=["raw/user_request.md", "context/project_summary.ko.md"],
        decisions=list(parsed.get("decisions", [])),
    )


def _validate_decision_coverage(
    sheet: RequirementLockSheet,
    answers: list[QAItem],
    feedback: str,
) -> None:
    """저장된 사용자 결정을 명세 항목이 빠짐없이 덮는지 확인한다."""
    decisions = [*sheet.mandatory_requirements, *sheet.constraints, *sheet.non_scope, *sheet.workflow_constraints]
    missing = [f"user_answer:{answer.question_id}" for answer in answers
               if not any(_covers_source(item, f"user_answer:{answer.question_id}") for item in decisions)]
    if feedback and not any(_covers_source(item, "user_feedback") for item in decisions):
        missing.append("user_feedback")
    if missing:
        error = _normalization_error("source_coverage", [f"Missing source in product requirements or workflow_constraints: {marker}" for marker in missing])
        error.code = "SOURCE_COVERAGE_MISSING"
        raise error


def _validate_preserved_mandatory_ids(
    previous_sheet: Any, current_sheet: RequirementLockSheet
) -> None:
    """확정된 필수 요구사항은 같은 ID의 최신 정규화 결과로만 바꾼다."""
    if not isinstance(previous_sheet, dict):
        return
    previous = RequirementLockSheet.from_dict(previous_sheet)
    old_ids = {item.id for item in previous.mandatory_requirements if item.id}
    current_ids = {item.id for item in current_sheet.mandatory_requirements if item.id}
    if not old_ids.issubset(current_ids):
        raise _normalization_error("mandatory_ids", [f"Preserve mandatory ID: {ident}" for ident in sorted(old_ids - current_ids)])


def _covers_source(item: RequirementItem, marker: str) -> bool:
    return (
        item.text.strip()
        and not _contains_hangul(item.text)
        and marker in {item.source, *item.sources}
    )


def _response_validation_error(parsed: Any) -> RequirementNormalizationError:
    if not isinstance(parsed, dict):
        return _normalization_error("structure", ["Response must be a JSON object."])
    details = [] if isinstance(parsed.get("workflow_constraints"), list) else ["workflow_constraints must be supplied as an array, separate from product requirements."]
    non_english = []
    for key in ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints", "non_scope"):
        items = parsed.get(key, [])
        if not isinstance(items, list) or (key == "mandatory_requirements" and not items):
            details.append(f"{key} must be an array; mandatory_requirements must not be empty.")
            continue
        for index, item in enumerate(items):
            path = f"{key}[{index}]"
            if isinstance(item, dict) and isinstance(item.get("text"), str) and _contains_hangul(item["text"]):
                non_english.append(f"Normalize {path}.text to English; preserve original wording in original_text.")
            elif not _valid_requirement_item(item):
                details.append(f"{path} must have a valid id, single-line English text, source, and optional original_text and sources.")
        if key == "mandatory_requirements":
            ids = [item.get("id") for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]
            if len(ids) != len(set(ids)):
                details.append("mandatory_requirements contains duplicate IDs.")
    unresolved = parsed.get("unresolved_questions", [])
    if not isinstance(unresolved, list) or unresolved:
        details.append("unresolved_questions must be an empty array.")
    return _normalization_error("english_normalization" if non_english else "structure", non_english + details)


def _normalization_error(category: str, details: list[str]) -> RequirementNormalizationError:
    error = RequirementNormalizationError("Requirement lock response could not be normalized.")
    error.category = category
    error.validation_details = details
    return error


def _contains_hangul(value: str) -> bool:
    from backend.infrastructure.output_language import prose, has_hangul
    return has_hangul(prose(value))


def _valid_lock_response(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("workflow_constraints"), list):
        return False
    requirements = value.get("mandatory_requirements")
    if not isinstance(requirements, list) or not requirements:
        return False
    if not all(_valid_requirement_item(item) for item in requirements):
        return False
    if len({item["id"] for item in requirements}) != len(requirements):
        return False
    for key in (
        "recommended_requirements",
        "optional_requirements",
        "non_scope",
        "constraints",
    ):
        raw_items = value.get(key, [])
        if not isinstance(raw_items, list) or not all(
            _valid_requirement_item(item) for item in raw_items
        ):
            return False
    for item in value["workflow_constraints"]:
        if not _valid_requirement_item(item) or not item["id"].startswith("WF-") or not item.get("original_text", "").strip():
            return False
    if any(item["id"].startswith("WF-") for group in ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints", "non_scope") for item in value.get(group, [])):
        return False
    unresolved = value.get("unresolved_questions", [])
    if not isinstance(unresolved, list) or unresolved:
        return False
    return True


def _valid_requirement_item(item: Any) -> bool:
    if not isinstance(item, dict) or not all(
        isinstance(item.get(key), str) and item[key].strip()
        for key in ("id", "text", "source")
    ):
        return False
    if (
        not _REQUIREMENT_ID.match(item["id"])
        or "\n" in item["text"]
        or item["text"].lstrip().startswith("#")
        or _contains_hangul(item["text"])
    ):
        return False
    original = item.get("original_text", "")
    if not isinstance(original, str):
        return False
    raw_sources = item.get("sources", [])
    return isinstance(raw_sources, list) and all(
        isinstance(source, str) and _valid_source(source) for source in raw_sources
    ) and _valid_source(item["source"])


_REQUIREMENT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9_]$")


def _valid_source(value: str) -> bool:
    if value in {"user_request", "user_feedback"}:
        return True
    if re.fullmatch(r"project_decision:[0-9a-f]{32}:[1-9][0-9]*", value):
        return True
    return bool(re.fullmatch(r"user_answer:[A-Za-z0-9_-]+", value))
