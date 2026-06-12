"""Spec Interviewer — classifies request and identifies blocking questions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from magi_spec.core.provider_output import extract_json_object
from magi_spec.interview.question_templates import (
    Question,
    classify_request_type,
    select_questions,
)
from magi_spec.schemas.requirement_lock import QAItem


@dataclass(slots=True)
class InterviewResult:
    request_type: str
    blocking_questions: list[str]
    assumptions: list[str]
    pre_answers: list[QAItem] = field(default_factory=list)
    direction_changing_pending: bool = False


class SpecInterviewer:
    """Single-pass interviewer using the Interviewer LLM route."""

    agent_id = "interviewer"

    def run(
        self,
        state: dict[str, Any],
        manifest: dict[str, Any],
        *,
        provider_complete_fn: Any,  # callable(prompt: str) -> str
    ) -> InterviewResult:
        user_request = state.get("user_request", "").strip()
        request_type = classify_request_type(user_request, manifest)
        questions = select_questions(request_type, answered_ids=set())

        if not user_request:
            return InterviewResult(
                request_type=request_type,
                blocking_questions=["사용자 요청이 비어 있어 구현 방향을 결정할 수 없습니다."],
                assumptions=[],
                direction_changing_pending=True,
            )

        prompt = _build_prompt(user_request, questions)
        try:
            raw = provider_complete_fn(prompt)
            parsed = extract_json_object(raw)
        except Exception:
            parsed = None

        return _parse_result(parsed, request_type=request_type, questions=questions)


def _build_prompt(user_request: str, questions: list[Question]) -> str:
    q_lines = "\n".join(
        f"- [{q.question_id}] (direction_changing={q.direction_changing}) {q.text}"
        for q in questions
    )
    return (
        f"You are analyzing the following user development request:\n\n"
        f"{user_request[:3000]}\n\n"
        f"For each question below, determine if it is already answered by the request "
        f"(provide an answer) or if it is genuinely unresolved (mark as blocking).\n\n"
        f"Questions:\n{q_lines}\n\n"
        f"Return JSON with keys:\n"
        f"  request_type: string (product|feature|bugfix|refactor|infra)\n"
        f"  assumptions: list of Korean strings (inferred answers from the request)\n"
        f"  blocking_questions: list of Korean strings (unanswered direction-changing questions)\n"
        f"  pre_answers: list of {{question_id, question, answer}} for answered questions\n"
        f"Return ONLY valid JSON."
    )


def _parse_result(
    parsed: dict[str, Any] | None,
    *,
    request_type: str,
    questions: list[Question],
) -> InterviewResult:
    if not isinstance(parsed, dict):
        # Fallback: use template questions as-is
        direction_changing_pending = any(q.direction_changing for q in questions)
        return InterviewResult(
            request_type=request_type,
            blocking_questions=[],  # don't block on LLM failure — use templates as assumptions
            assumptions=[
                "사용자가 명시하지 않은 세부 구현 방식은 기존 프로젝트 관례를 우선한다.",
                "최종 산출물은 구현 에이전트가 바로 사용할 수 있는 영어 Markdown 명세다.",
            ],
            direction_changing_pending=False,
        )

    raw_type = str(parsed.get("request_type", request_type))
    from magi_spec.interview.question_templates import QUESTION_SETS
    if raw_type not in QUESTION_SETS and raw_type != "feature":
        raw_type = request_type

    assumptions = _as_str_list(parsed.get("assumptions"))
    blocking = _as_str_list(parsed.get("blocking_questions"))
    raw_answers = parsed.get("pre_answers", [])
    pre_answers = []
    if isinstance(raw_answers, list):
        for item in raw_answers:
            if isinstance(item, dict):
                pre_answers.append(QAItem.from_dict(item))

    # Only mark direction_changing_pending if any blocking question originated from
    # a direction-changing template question.
    direction_changing_ids = {q.question_id for q in questions if q.direction_changing}
    answered_ids = {a.question_id for a in pre_answers}
    has_unanswered_dc = bool(direction_changing_ids - answered_ids) and bool(blocking)

    return InterviewResult(
        request_type=raw_type,
        blocking_questions=blocking,
        assumptions=assumptions,
        pre_answers=pre_answers,
        direction_changing_pending=has_unanswered_dc,
    )


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
