"""Structured provider packet parsing for MAGI workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


VALID_REVIEW_STATUS = {"PASS", "REVISE", "FAIL"}


def normalize_review_status(value: Any, *, default: str = "PASS") -> str:
    status = str(value or default).upper()
    if status in VALID_REVIEW_STATUS:
        return status
    return default


def stringify_markdown(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value:
        return json.dumps(value, ensure_ascii=False, indent=2)
    return fallback


def normalize_section_status(
    value: Any,
    *,
    base: dict[str, str],
    default_on_invalid: str = "REVISE",
) -> dict[str, str]:
    section_status = dict(base)
    if not isinstance(value, dict):
        return section_status
    for section in base:
        if section in value:
            section_status[section] = normalize_review_status(
                value[section],
                default=default_on_invalid,
            )
    return section_status


@dataclass(slots=True)
class ReviewPacket:
    status: str
    content: str
    section_status: dict[str, str]

    @classmethod
    def from_provider_dict(
        cls,
        data: dict[str, Any] | None,
        *,
        fallback_status: str,
        fallback_content: str,
        fallback_sections: dict[str, str],
        allow_static_fallback: bool,
        malformed_error_title: str,
    ) -> "ReviewPacket":
        if not isinstance(data, dict):
            if allow_static_fallback:
                return cls(
                    status=fallback_status,
                    content=fallback_content,
                    section_status=dict(fallback_sections),
                )
            return cls(
                status="REVISE",
                content="\n".join(
                    [
                        malformed_error_title,
                        "",
                        "- provider 응답이 요구된 JSON 계약을 만족하지 않아 재검토가 필요합니다.",
                        "- `status`, `section_status`, `content` 키를 포함한 JSON만 유효합니다.",
                    ]
                ),
                section_status={key: "REVISE" for key in fallback_sections},
            )

        return cls(
            status=normalize_review_status(data.get("status"), default=fallback_status),
            content=stringify_markdown(data.get("content"), fallback_content),
            section_status=normalize_section_status(
                data.get("section_status"),
                base=fallback_sections,
            ),
        )


@dataclass(slots=True)
class AnalysisPacket:
    intent_parse: str
    requirement_lock: str
    scope_classification: str
    assumptions: list[str]
    blocking_questions: list[str]

    @classmethod
    def from_provider_dict(
        cls,
        data: dict[str, Any] | None,
        *,
        fallback_intent: str,
        fallback_requirement_lock: str,
        fallback_scope: str,
        fallback_assumptions: list[str],
        fallback_blocking_questions: list[str],
    ) -> "AnalysisPacket":
        if not isinstance(data, dict):
            return cls(
                intent_parse=fallback_intent,
                requirement_lock=fallback_requirement_lock,
                scope_classification=fallback_scope,
                assumptions=list(fallback_assumptions),
                blocking_questions=list(fallback_blocking_questions),
            )
        return cls(
            intent_parse=stringify_markdown(data.get("intent_parse"), fallback_intent),
            requirement_lock=stringify_markdown(
                data.get("requirement_lock"),
                fallback_requirement_lock,
            ),
            scope_classification=stringify_markdown(
                data.get("scope_classification"),
                fallback_scope,
            ),
            assumptions=_as_string_list(data.get("assumptions"), fallback_assumptions),
            blocking_questions=_as_string_list(
                data.get("blocking_questions"),
                fallback_blocking_questions,
            ),
        )


def choose_spec_markdown(
    data: dict[str, Any] | None,
    *,
    raw_output: str,
    fallback: str,
) -> str:
    if isinstance(data, dict):
        return stringify_markdown(
            data.get("spec_markdown") or data.get("content"),
            fallback,
        )
    if raw_output.lstrip().startswith("#"):
        return raw_output.strip()
    return fallback


def choose_critical_report_markdown(
    data: dict[str, Any] | None,
    *,
    raw_output: str,
    fallback: str,
) -> str:
    if isinstance(data, dict):
        return stringify_markdown(
            data.get("critical_report_markdown") or data.get("content"),
            fallback,
        )
    if raw_output.lstrip().startswith("#"):
        return raw_output.strip()
    return fallback


def _as_string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    strings = [str(item).strip() for item in value if str(item).strip()]
    if not strings:
        return list(fallback)
    return strings
