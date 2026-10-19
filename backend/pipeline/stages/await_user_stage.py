"""사용자 답변 대기 단계."""

from __future__ import annotations
from typing import Any
from backend.models import STATUS_NEEDS_USER_INPUT
from backend.models import WorkflowState


class AwaitUserStage:
    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        return {"status": STATUS_NEEDS_USER_INPUT,
                "blocking_questions": list(state.get("blocking_questions", [])),
                "awaiting_input_reason": state.get("awaiting_input_reason"),
                "question_forms": state.get("question_forms", {}),
                "review_questions": list(state.get("review_questions", []))}
