"""승인 후보 생성 단계."""

from __future__ import annotations
from typing import Any
from backend.errors import InvalidStateError
from backend.models import STATUS_CRITICAL_BLOCKED, STATUS_PASS_PENDING_USER_APPROVAL
from backend.models import RequirementLockSheet
from backend.models import WorkflowState
from backend.models import parse_issue_list, count_unresolved_required
from backend.pipeline.context import PipelineContext


class CandidateStage:
    def __init__(self, context: PipelineContext) -> None:
        self.context = context

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        issues = parse_issue_list(state.get("structured_issues", []))
        if state.get("blocking_questions") or count_unresolved_required(issues) or any(
            issue.resolution_kind == "user_decision" and issue.status != "resolved" for issue in issues
        ):
            raise InvalidStateError("Approval candidate still has unresolved required review issues.")
        created = list(state.get("created_artifacts", []))
        path = "draft/approval_candidate_spec.en.md"
        try:
            spec = self.context.writer.read_text(path)
        except Exception:
            spec = ""
        if not spec or not self.context.compiler.english_only(spec):
            raise InvalidStateError("Reviewed candidate is missing or invalid.")
        if path not in created:
            created.append(path)
        return {
            "status": STATUS_PASS_PENDING_USER_APPROVAL,
            "approval_candidate_spec": str(self.context.writer.path(path)),
            "user_approval_status": "PENDING",
            "final_agent_spec": None,
            "created_artifacts": created,
        }
