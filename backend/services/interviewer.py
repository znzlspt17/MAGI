"""요청에서 실제 방향을 바꾸는 미결정만 확인한다."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from backend.errors import InvalidStateError
from backend.infrastructure.prompt_messages import complete as complete_messages
from backend.infrastructure.prompt_messages import flatten
from backend.infrastructure.prompt_messages import messages as build_messages
from backend.infrastructure.prompts import load_prompt
from backend.infrastructure.provider_output import extract_json_object
from backend.models import InterviewResult
from backend.models import InterviewResponse
from backend.models import QAItem
from backend.services.questions import (
    HARD_CAP,
    QUESTION_SETS,
    Question,
    classify_request_type,
    select_questions,
)


class SpecInterviewer:
    agent_id = "interviewer"

    def run(
        self,
        state: dict[str, Any],
        manifest: dict[str, Any],
        *,
        provider_complete_fn: Any | None = None,
        provider_messages_fn: Any | None = None,
    ) -> InterviewResult:
        request = str(state.get("user_request", "")).strip()
        request_type = classify_request_type(request, manifest)
        explicit_answers, inferred_answers = _saved_answers(state)
        answers = _merge_answers(inferred_answers, explicit_answers)
        all_questions = _all_questions(request_type, answers)
        candidates = select_questions(
            request_type, answered_ids={item.question_id for item in answers}
        )

        if not request:
            return InterviewResult(
                request_type,
                ["[REQUEST] 사용자 요청이 비어 있습니다."],
                [],
                answers,
                True,
            )

        payload = _build_messages(request, manifest, candidates, answers, state)
        raw = complete_messages(
            payload,
            provider_complete_fn=provider_complete_fn,
            provider_messages_fn=provider_messages_fn,
        )
        if isinstance(raw, InterviewResponse):
            parsed = _normalise_response(raw.model_dump())
            if parsed is None:
                raise InvalidStateError("Interview response schema is invalid.")
        else:
            # 문자열 콜백은 기존 직접 서비스 호출의 호환 경계에서만 처리한다.
            parsed, _ = _parse_response(raw)
            if parsed is None:
                raise InvalidStateError("Interview response schema is invalid.")

        parsed_type = str(parsed["request_type"])
        request_type = parsed_type
        all_questions = _all_questions(request_type, answers)
        inferred = [
            QAItem.from_dict(item)
            for item in parsed["pre_answers"]
            if isinstance(item, dict)
        ]
        answers = _merge_answers(
            _merge_answers(inferred_answers, inferred),
            explicit_answers,
        )
        answered_ids = {item.question_id for item in answers}
        answered_text = {_normalise(item.question) for item in answers if item.question}

        blocking: list[str] = []
        forms = {}
        from backend.services.question_forms import question_form
        for item in [
            *parsed["blocking_questions"],
            *parsed.get("additional_questions", []),
        ]:
            question_id, text = _identify_question(item, all_questions)
            if (
                text
                and question_id not in answered_ids
                and _normalise(text) not in answered_text
            ):
                blocking.append(f"[{question_id}] {text}")
                try:
                    forms.setdefault(question_id, question_form(question_id, text, {k: item[k] for k in ("input_type", "options") if k in item} if isinstance(item, dict) else {}))
                except ValueError as error:
                    raise InvalidStateError("Interview question form is invalid.") from error

        return InterviewResult(
            request_type,
            list(dict.fromkeys(blocking))[:HARD_CAP],
            _string_list(parsed["assumptions"]),
            answers,
            bool(blocking),
            {key: form for key, form in forms.items() if any(q.startswith(f"[{key}]") for q in list(dict.fromkeys(blocking))[:HARD_CAP])},
        )


def _build_messages(
    request: str,
    manifest: dict[str, Any],
    candidates: list[Question],
    answers: list[QAItem],
    state: dict[str, Any],
) -> list[dict[str, str]]:
    summary = {
        "root": manifest.get("root"),
        "file_count": manifest.get("file_count", 0),
        "files": [item.get("path") for item in manifest.get("files", [])],
        "request_types": sorted(QUESTION_SETS),
        "saved_answers": [item.to_dict() for item in answers],
        "validated_requirements": state.get("requirement_lock_sheet"),
        "actual_user_sources": state.get("confirmed_user_sources", {}),
    }
    candidate_text = "\n".join(
        f"- [{item.question_id}] {item.text}" for item in candidates
    ) or "- none"
    history = state.get("revision_history", [])
    history_text = "\n\n".join(
        str(item) for item in history if isinstance(item, str) and item.strip()
    )
    original = str(state.get("original_user_request") or request)
    return build_messages(
        load_prompt("interviewer"),
        original,
        json.dumps(summary, ensure_ascii=False, indent=2),
        ("Revision feedback history", history_text),
        ("Latest revision feedback", str(state.get("revision_feedback") or "")),
        ("Candidate questions", candidate_text),
    )


def _build_prompt(
    request: str,
    manifest: dict[str, Any],
    candidates: list[Question],
    answers: list[QAItem],
    state: dict[str, Any],
) -> str:
    """기존 문자열 콜백 검증용 호환 진입점이다."""
    return flatten(_build_messages(request, manifest, candidates, answers, state))


def _saved_answers(state: dict[str, Any]) -> tuple[list[QAItem], list[QAItem]]:
    explicit_raw = []
    if isinstance(state.get("requirement_lock_sheet"), dict):
        explicit_raw = state["requirement_lock_sheet"].get("user_answers", [])
    inferred_raw = state.get("interview_pre_answers", [])
    return (
        [QAItem.from_dict(item) for item in explicit_raw if isinstance(item, dict)],
        [QAItem.from_dict(item) for item in inferred_raw if isinstance(item, dict)],
    )


def _merge_answers(inferred: list[QAItem], explicit: list[QAItem]) -> list[QAItem]:
    merged = {
        item.question_id: item
        for item in inferred
        if item.question_id and item.answer.strip()
    }
    merged.update(
        {
            item.question_id: item
            for item in explicit
            if item.question_id and item.answer.strip()
        }
    )
    return list(merged.values())


def _all_questions(request_type: str, answers: list[QAItem]) -> dict[str, str]:
    questions = select_questions(request_type, answered_ids=set())
    known = {question.question_id: question.text for question in questions}
    for answer in answers:
        if answer.question_id:
            known.setdefault(answer.question_id, answer.question)
    return known


def _valid_response(value: Any) -> bool:
    """호환성을 위해 유지하는 응답 스키마 검사 진입점."""
    return _normalise_response(value) is not None


def _parse_response(raw: Any) -> tuple[dict[str, Any] | None, str]:
    try:
        parsed = extract_json_object(raw)
    except (AttributeError, TypeError):
        return None, "INTERVIEW_JSON_PARSE"
    if parsed is None:
        return None, "INTERVIEW_JSON_PARSE"
    normalised = _normalise_response(parsed)
    if normalised is None:
        return None, "INTERVIEW_SCHEMA"
    return normalised, ""


def _normalise_response(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    request_type = value.get("request_type")
    if not isinstance(request_type, str) or request_type not in QUESTION_SETS:
        return None
    blocking_questions = value.get("blocking_questions")
    if not _is_question_list(blocking_questions):
        return None

    normalised = dict(value)
    normalised["blocking_questions"] = blocking_questions
    for field in ("assumptions", "additional_questions", "pre_answers"):
        item = normalised.get(field)
        if item is None:
            normalised[field] = []
    assumptions = normalised["assumptions"]
    additional_questions = normalised["additional_questions"]
    pre_answers = normalised["pre_answers"]
    if not _is_string_list(assumptions):
        return None
    if not _is_question_list(additional_questions):
        return None
    if not _is_pre_answer_list(pre_answers):
        return None
    normalised["assumptions"] = [item.strip() for item in assumptions if item.strip()]
    return normalised


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_question_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if isinstance(item, str) and item.strip():
            continue
        if not isinstance(item, dict):
            return False
        text = item.get("question", item.get("text"))
        if not isinstance(text, str) or not text.strip():
            return False
        question_id = item.get("question_id")
        if question_id is not None and not isinstance(question_id, str):
            return False
    return True


def _is_pre_answer_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        if (
            not isinstance(item.get("question_id"), str)
            or not item["question_id"].strip()
        ):
            return False
        if not isinstance(item.get("answer"), str) or not item["answer"].strip():
            return False
        question = item.get("question", "")
        if not isinstance(question, str):
            return False
    return True


def _identify_question(value: Any, known: dict[str, str]) -> tuple[str, str]:
    if isinstance(value, dict):
        question_id = str(value.get("question_id", "")).strip()
        text = str(value.get("question", value.get("text", ""))).strip()
    else:
        text = str(value).strip()
        match = re.match(r"\[([^]]+)]\s*(.*)", text)
        question_id = match.group(1) if match else ""
        text = match.group(2) if match else text
    if question_id in known:
        return question_id, text or known[question_id]
    digest = hashlib.sha256(_normalise(text).encode()).hexdigest()[:10]
    return f"FOLLOWUP-{digest}", text


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()]


def _normalise(value: str) -> str:
    text = re.sub(r"^\s*\[[^]]+\]\s*", "", value)
    return " ".join(text.casefold().split())
