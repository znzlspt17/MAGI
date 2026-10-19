"""체크리스트 검토 단계."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from backend.models import (
    count_unresolved_blocking,
    count_unresolved_required,
)
from backend.models import STATUS_CRITIQUING
from backend.models import RequirementLockSheet
from backend.models import WorkflowState
from backend.infrastructure.provider_call import complete_with_usage
from backend.models import ReviewResponse
from backend.pipeline.context import PipelineContext


class ReviewStage:
    def __init__(self, context: PipelineContext) -> None:
        self.context = context

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        spec_path = state.get("approval_candidate_spec", "")
        try:
            spec = Path(spec_path).read_text(encoding="utf-8") if spec_path else ""
        except Exception:
            spec = ""
        if not spec:
            try:
                spec = self.context.writer.read_text(
                    "draft/approval_candidate_spec.en.md"
                )
            except Exception:
                spec = ""
        sheet_data = state.get("requirement_lock_sheet")
        from backend.services.workflow_constraints import validate_locked_sources
        sheet = validate_locked_sources(RequirementLockSheet.from_dict(sheet_data).require_validated(), state)
        route = self.context.config.model_routing[self.context.critic.agent_id]
        provider = self.context.provider

        def complete(messages: list[dict[str, str]]) -> ReviewResponse:
            return complete_with_usage(
                self.context.writer,
                provider,
                messages,
                model=route.model,
                stage="checklist_critic",
                temperature=0,
            )

        issues = self.context.critic.critique(
            spec,
            sheet,
            provider_messages_fn=complete,
            user_request=str(
                state.get("original_user_request") or state.get("user_request", "")
            ),
            previous_issues=state.get("structured_issues", []),
            revision_feedback=str(state.get("revision_feedback", "")),
            revision_history=list(state.get("revision_history", [])),
        )
        history = list(state.get("review_history", []))
        issue_data = [item.to_dict() for item in issues]
        passes = int(state.get("critic_pass_count", 0)) + 1
        history.append({"review_round": len(history) + 1, "pass": passes, "issues": issue_data})
        self.context.writer.write_json(
            "review/checklist_issues.json",
            {
                "pass": passes,
                "unresolved_blocking": count_unresolved_blocking(issues),
                "unresolved_required": count_unresolved_required(issues),
                "issues": issue_data,
            },
            overwrite=True,
        )
        if "review/checklist_issues.json" not in created:
            created.append("review/checklist_issues.json")
        return {
            "status": STATUS_CRITIQUING,
            "structured_issues": issue_data,
            "critic_pass_count": passes,
            "blocking_questions": [],
            "awaiting_input_reason": None,
            "review_history": history,
            "created_artifacts": created,
        }
