"""Requirement Lock builder for v2 pipeline."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from magi_spec.core.provider_output import extract_json_object
from magi_spec.interview.interviewer import InterviewResult
from magi_spec.schemas.requirement_lock import (
    AssumptionItem,
    QAItem,
    RequirementItem,
    RequirementLockSheet,
)


class RequirementLockBuilder:
    """Builds a RequirementLockSheet from an InterviewResult using one LLM call."""

    agent_id = "interviewer"

    def build(
        self,
        state: dict[str, Any],
        manifest: dict[str, Any],
        interview: InterviewResult,
        *,
        provider_complete_fn: Any,  # callable(prompt: str) -> str
    ) -> RequirementLockSheet:
        user_request = state.get("user_request", "").strip()
        prompt = _build_prompt(user_request, interview)
        try:
            raw = provider_complete_fn(prompt)
            parsed = extract_json_object(raw)
        except Exception:
            parsed = None

        return _parse_sheet(parsed, interview=interview, user_request=user_request)


def _build_prompt(user_request: str, interview: InterviewResult) -> str:
    assumptions_text = "\n".join(f"- {a}" for a in interview.assumptions) or "- (없음)"
    blocking_text = (
        "\n".join(f"- {b}" for b in interview.blocking_questions) or "- (없음)"
    )
    pre_answers_text = (
        "\n".join(f"- [{a.question_id}] {a.question}: {a.answer}" for a in interview.pre_answers)
        or "- (없음)"
    )
    return (
        f"Given the following user request and interview analysis, produce a structured "
        f"Requirement Lock Sheet.\n\n"
        f"User Request:\n{user_request[:3000]}\n\n"
        f"Request Type: {interview.request_type}\n"
        f"Assumptions inferred:\n{assumptions_text}\n"
        f"Pre-answered questions:\n{pre_answers_text}\n"
        f"Unresolved blocking questions:\n{blocking_text}\n\n"
        f"Return JSON with keys:\n"
        f"  request_summary: string (one sentence English summary)\n"
        f"  mandatory_requirements: list of {{id, text, source}} objects\n"
        f"  recommended_requirements: list of {{id, text, source}} objects\n"
        f"  optional_requirements: list of {{id, text, source}} objects\n"
        f"  non_scope: list of {{id, text, source}} objects\n"
        f"  assumptions: list of {{id, text, risk}} objects (risk: low|medium|high)\n"
        f"  constraints: list of {{id, text, source}} objects\n"
        f"  acceptance_criteria_seed: list of strings\n"
        f"  unresolved_questions: list of strings\n\n"
        f"RULES:\n"
        f"- mandatory must include only what the user EXPLICITLY requested.\n"
        f"- non_scope must include 'MAGI does not implement the target project directly.'\n"
        f"- unresolved_questions = the blocking_questions above.\n"
        f"Return ONLY valid JSON."
    )


def _parse_sheet(
    parsed: dict[str, Any] | None,
    *,
    interview: InterviewResult,
    user_request: str,
) -> RequirementLockSheet:
    if not isinstance(parsed, dict):
        return RequirementLockSheet.build_fallback(
            request_type=interview.request_type,
            request_summary=user_request[:200] if user_request else "",
            blocking_questions=interview.blocking_questions,
            assumptions=interview.assumptions or None,
        )

    def _req_list(key: str, prefix: str) -> list[RequirementItem]:
        raw = parsed.get(key, [])
        if not isinstance(raw, list):
            return []
        result = []
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                result.append(RequirementItem.from_dict(item))
            elif isinstance(item, str) and item.strip():
                result.append(RequirementItem(
                    id=f"{prefix}-{i+1:03d}", text=item.strip(), source="user_request"
                ))
        return result

    def _asm_list() -> list[AssumptionItem]:
        raw = parsed.get("assumptions", [])
        if not isinstance(raw, list):
            return []
        result = []
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                result.append(AssumptionItem.from_dict(item))
            elif isinstance(item, str) and item.strip():
                result.append(AssumptionItem(
                    id=f"ASM-{i+1:03d}", text=item.strip(), risk="low"
                ))
        return result

    def _str_list(key: str) -> list[str]:
        raw = parsed.get(key, [])
        if isinstance(raw, list):
            return [str(s).strip() for s in raw if str(s).strip()]
        return []

    mandatory = _req_list("mandatory_requirements", "REQ")
    non_scope = _req_list("non_scope", "NS")

    # Guarantee non_scope always has the core MAGI invariant
    core_ns_text = "MAGI does not implement the target project directly."
    if not any(core_ns_text.lower() in r.text.lower() for r in non_scope):
        non_scope.insert(0, RequirementItem(
            id="NS-000", text=core_ns_text, source="system"
        ))

    return RequirementLockSheet(
        lock_id=f"lock_{uuid4().hex[:8]}",
        request_type=interview.request_type,
        request_summary=str(parsed.get("request_summary", user_request[:200])),
        user_answers=list(interview.pre_answers),
        mandatory_requirements=mandatory,
        recommended_requirements=_req_list("recommended_requirements", "REC"),
        optional_requirements=_req_list("optional_requirements", "OPT"),
        non_scope=non_scope,
        assumptions=_asm_list(),
        constraints=_req_list("constraints", "CON"),
        acceptance_criteria_seed=_str_list("acceptance_criteria_seed"),
        unresolved_questions=list(interview.blocking_questions),
        source_refs=["raw/user_request.md", "context/project_summary.ko.md"],
    )
