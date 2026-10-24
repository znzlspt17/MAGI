"""저장된 사용자 답변을 안전하게 복구하는 작은 도우미."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.models import QAItem


def saved_answers(state: Mapping[str, Any]) -> list[QAItem]:
    """현재 상태의 명시 답변을 우선하고 인터뷰의 사전 답변을 보충한다."""
    explicit, inferred = _state_answer_records(state)
    merged = _answer_map(explicit)
    for item in inferred:
        merged.setdefault(item.question_id, item)
    return list(merged.values())


def saved_answer_dicts(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in saved_answers(state)]


def _state_answer_records(state: Mapping[str, Any]) -> tuple[list[QAItem], list[QAItem]]:
    explicit: list[QAItem] = []
    lock_sheet = state.get("requirement_lock_sheet")
    if isinstance(lock_sheet, Mapping):
        explicit = _qa_items(lock_sheet.get("user_answers"))
    inferred = _qa_items(state.get("interview_pre_answers"))
    return explicit, inferred


def _answer_map(items: list[QAItem]) -> dict[str, QAItem]:
    result: dict[str, QAItem] = {}
    for item in items:
        result.setdefault(item.question_id, item)
    return result


def _qa_items(value: object) -> list[QAItem]:
    if not isinstance(value, list):
        return []
    result: list[QAItem] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        question_id = item.get("question_id")
        question = item.get("question")
        answer = item.get("answer")
        if not all(isinstance(field, str) for field in (question_id, question, answer)):
            continue
        if not question_id.strip() or not answer.strip():
            continue
        result.append(
            QAItem(
                question_id=question_id.strip(),
                question=question.strip(),
                answer=answer,
                selection=item.get("selection"),
            )
        )
    return result
