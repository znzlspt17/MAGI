"""저장된 사용자 답변을 안전하게 복구하는 작은 도우미."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.models import QAItem


def saved_answers(
    state: Mapping[str, Any],
    *,
    legacy_lock_sheet: object = None,
    pending_questions: list[str] | None = None,
) -> list[QAItem]:
    """상태 답변을 우선하고, 동일 잠금의 검증된 이전 답변만 보충한다."""
    explicit, inferred = _state_answer_records(state)
    merged = _answer_map(explicit)
    if _legacy_lock_matches(state, legacy_lock_sheet):
        for item in _qa_items(legacy_lock_sheet.get("user_answers")):
            if item.question_id in merged:
                continue
            if _matches_pending_question(item, pending_questions or []):
                merged[item.question_id] = item
    for item in inferred:
        merged.setdefault(item.question_id, item)
    return list(merged.values())


def saved_answer_dicts(
    state: Mapping[str, Any],
    *,
    legacy_lock_sheet: object = None,
    pending_questions: list[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        item.to_dict()
        for item in saved_answers(
            state,
            legacy_lock_sheet=legacy_lock_sheet,
            pending_questions=pending_questions,
        )
    ]


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


def _legacy_lock_matches(state: Mapping[str, Any], legacy_lock_sheet: object) -> bool:
    if not isinstance(legacy_lock_sheet, Mapping):
        return False
    legacy_lock_id = legacy_lock_sheet.get("lock_id")
    if not isinstance(legacy_lock_id, str) or not legacy_lock_id.strip():
        return False
    state_lock = state.get("requirement_lock_sheet")
    if not isinstance(state_lock, Mapping):
        return True
    state_lock_id = state_lock.get("lock_id")
    return (
        isinstance(state_lock_id, str)
        and bool(state_lock_id.strip())
        and state_lock_id == legacy_lock_id
    )


def _matches_pending_question(answer: QAItem, pending_questions: list[str]) -> bool:
    for question in pending_questions:
        parsed = _pending_question_parts(question)
        if parsed is None:
            continue
        question_id, question_text = parsed
        if answer.question_id != question_id:
            continue
        if _normalize_question_text(answer.question) == question_text:
            return True
    return False


def _pending_question_parts(question: object) -> tuple[str, str] | None:
    if not isinstance(question, str):
        return None
    if not question.startswith("[") or "]" not in question:
        return None
    question_id, body = question[1:].split("]", 1)
    normalized_id = question_id.strip()
    normalized_body = _normalize_question_text(body)
    if not normalized_id or not normalized_body:
        return None
    return normalized_id, normalized_body


def _normalize_question_text(question: str) -> str:
    text = question.strip()
    if text.startswith("[") and "]" in text:
        text = text.split("]", 1)[1]
    return " ".join(text.split())
