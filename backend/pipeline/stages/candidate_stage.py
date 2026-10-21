"""승인 후보 생성 단계."""

from __future__ import annotations
from typing import Any
import logging
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
        # 변경 검토는 안내 기능이며 승인 후보 검증 결과를 바꾸지 않는다.
        from backend.services.change_review import review_candidate, CURRENT_REVIEW, digest, normalize
        try:
            review_candidate(self.context, state, spec)
        except Exception as exc:
            logging.getLogger(__name__).warning("change review unavailable exception_type=%s", type(exc).__name__)
            try:
                self.context.writer.write_json_atomic(CURRENT_REVIEW, {
                    "status": "failed", "reason": "analysis_failed", "changes": [], "sources": [],
                    "after_hash": digest(normalize(spec)), "analysed": 0, "remaining": None,
                })
            except Exception:
                logging.getLogger(__name__).warning("change review failure could not be saved")
        return {
            "status": STATUS_PASS_PENDING_USER_APPROVAL,
            "approval_candidate_spec": str(self.context.writer.path(path)),
            "user_approval_status": "PENDING",
            "final_agent_spec": None,
            "created_artifacts": created,
        }
