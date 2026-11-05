"""Checklist Critic for v2 pipeline."""

from __future__ import annotations

import json
import re
from typing import Any
from backend.errors import ReviewValidationError
from backend.infrastructure.output_language import has_hangul, prose

from backend.models import ReviewResponse
from backend.infrastructure.prompt_messages import messages as build_messages
from backend.infrastructure.prompts import load_prompt
from backend.models import (
    IssuePacket,
    merge_issue_lists,
    parse_issue_list,
)
from backend.models import RequirementLockSheet
from backend.services.checklist import run_deterministic_checks

# 2026-11-04: 검사 식별자를 설명하되 입력에서 추출한 원문이나 실패 위치는 전달하지 않는다.
_DETERMINISTIC_DESCRIPTIONS = {
    "SEC-REQUIRED-001": "필수 명세 제목이 누락되었습니다.",
    "SEC-REQUIRED-ORDER-001": "필수 명세 제목의 순서가 올바르지 않습니다.",
    "SCOPE-NONSCOPE-001": "범위 제외 섹션이 비어 있습니다.",
    "FORBIDDEN-001": "금지 행동 섹션이 비어 있습니다.",
    "AC-001": "수용 기준 섹션이 비어 있습니다.",
    "AC-QUALITY-001": "수용 기준에 일반적인 자리표시자가 있습니다.",
    "TEST-001": "테스트 계획 섹션이 비어 있습니다.",
    "UNRESOLVED-Q-001": "필수 질문이 해결되지 않았습니다.",
    "AMBIG-001": "확정 요구사항에 관찰 가능한 기준과 테스트가 필요합니다.",
    "LOCK-COVER-001": "확정 요구사항이나 제품 결정이 명세에서 누락·중복·변경되었습니다.",
}


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
        provider_messages_fn: Any,
        user_request: str = "",
        previous_issues: list[IssuePacket] | list[dict[str, Any]] | None = None,
        revision_feedback: str = "",
        revision_history: list[str] | None = None,
        rubric: dict[str, Any] | None = None,
        evaluation_sink: Any = None,
    ) -> list[IssuePacket]:
        sheet.require_validated()
        # 1. 결정적 검사 (always authoritative, no LLM needed)
        deterministic = run_deterministic_checks(spec_md, sheet)
        # 2026-11-04: 결정적 결함은 별도 병합하므로 모델에는 안전한 요약과 점수 상한만 제공한다.
        from backend.services.rubric import deterministic_score_cap, apply_deterministic_evaluation
        deterministic_cap = deterministic_score_cap(deterministic)
        checks = sorted({(
            "LOCK-COVER-001" if item.checklist_id.startswith("LOCK-COVER-") else item.checklist_id,
            item.section, item.severity,
        ) for item in deterministic})

        # 2. LLM-assisted check (adds non-overlapping issues)
        payload = _build_messages(
            spec_md,
            sheet,
            user_request=user_request,
            previous_issues=previous_issues,
            revision_feedback=revision_feedback,
            revision_history=revision_history or [],
            rubric=rubric,
            deterministic_checks={"issues": [{"checklist_id": check, "section": section, "severity": severity,
                                               "description": _DETERMINISTIC_DESCRIPTIONS.get(check, "A deterministic specification check failed.")}
                                              for check, section, severity in checks],
                                  "score_cap": deterministic_cap},
        )
        raw = provider_messages_fn(payload)
        try:
            if not isinstance(raw, ReviewResponse):
                raise ReviewValidationError()
            evaluation = None
            if rubric is not None:
                from backend.services.rubric import validate_evaluation
                evaluation = validate_evaluation(raw, rubric, spec_md)
            parsed = raw.model_dump()
            for index, item in enumerate(parsed["issues"], start=1):
                item["issue_id"] = f"LLM-ISSUE-{index:03d}"
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
                absence_checks={(item.issue_checklist_id, item.section) for item in raw.rubric_verdicts
                                if rubric is not None and item.evidence_kind == "absence" and item.verdict != "PASS"},
            )
        except (AttributeError, TypeError):
            raise ReviewValidationError() from None

        # 3. Merge (deterministic wins on checklist_id collision)
        merged = merge_issue_lists(deterministic, llm_issues)
        if evaluation is not None:
            # 결정적 검사 결함을 모델 점수로 숨길 수 없다.
            evaluation = apply_deterministic_evaluation(evaluation, deterministic)
            if evaluation_sink is not None:
                evaluation_sink(evaluation)
        return merged


def _build_messages(
    spec_md: str,
    sheet: RequirementLockSheet,
    *,
    user_request: str,
    previous_issues: list[IssuePacket] | list[dict[str, Any]] | None,
    revision_feedback: str,
    revision_history: list[str],
    rubric: dict[str, Any] | None = None,
    deterministic_checks: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    history = "\n\n".join(item for item in revision_history if item.strip())
    product_sheet = sheet.to_dict()
    workflow = product_sheet.pop("workflow_constraints")
    canonical = json.dumps(product_sheet, ensure_ascii=False, indent=2)
    return build_messages(
        load_prompt("checklist_critic"),
        user_request,
        canonical,
        ("수정 의견 이력", history),
        ("최신 수정 의견", revision_feedback),
        ("이전 검토 이슈", _serialize_previous_issues(previous_issues)),
        ("명세 초안", spec_md),
        ("작업별 평가 기준", json.dumps({"items": rubric["items"]}, ensure_ascii=False) if rubric is not None else ""),
        ("결정적 검사", json.dumps(deterministic_checks, ensure_ascii=False) if deterministic_checks is not None else ""),
        workflow_constraints=workflow,
    )


def _parse_provider_issues(
    parsed: dict[str, Any] | None,
    known_requirement_ids: set[str],
    *,
    absence_checks: set[tuple[str | None, str]] | None = None,
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
                or (not entry["quote"].strip() and (item.get("checklist_id"), entry.get("source")) not in (absence_checks or set()))
            for entry in evidence
        ):
            raise ReviewValidationError(check="review_evidence")
        if item.get("defect_kind") not in {"requirements_gap", "spec_omission", "verification_gap", "confirmed_conflict"} or not all(
            isinstance(item.get(key), str) for key in ("resolution_reason", "missing_information", "decision_key")) or not item["resolution_reason"].strip() or not item["decision_key"].strip():
            raise ReviewValidationError(["Supply defect_kind, resolution_reason, missing_information and a stable decision_key."], check="review_classification")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,100}", item["decision_key"]):
            raise ReviewValidationError(["decision_key는 안정적인 영문 주제 식별자여야 합니다."], check="decision_key")
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
