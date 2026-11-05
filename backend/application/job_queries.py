"""작업 목록과 공개 상태 조회."""
from __future__ import annotations
import copy
from pathlib import Path
from backend.application.execution_history import ExecutionHistory
from backend.services.saved_answers import saved_answer_dicts

_ACTIVE = {"queued", "running"}


class JobQueries:
    def __init__(self, access):
        self.documents = access.documents
        self.get = access.get
        self.read_json = access.read_json
        self.read_text = access.read_text
        self.state = access.state

    def allowed(self, ident):
        job = self.get(ident)
        if job["status"] in _ACTIVE:
            return []
        if job["status"] in {"error", "interrupted"}:
            from backend.infrastructure.workflow_store import retry_state
            recovery = retry_state(self.documents(ident))
            return ["message", "retry"] if recovery["can_retry"] else ["message"]
        state = self.state(ident)
        if not state:
            return []
        if state.get("status") == "FINALIZED":
            return ["message", "continue"]
        from backend.services.refinement import needs_upgrade
        if needs_upgrade(state):
            return list(dict.fromkeys([action for action in state.get("allowed_actions", []) if action != "approve"] + ["retry"]))
        return state.get("allowed_actions", [])

    def summary(self, ident):
        job = self.get(ident)
        state = self.state(ident)
        actions = self.allowed(ident)
        recovery = {}
        if job["status"] in {"error", "interrupted"}:
            from backend.infrastructure.workflow_store import retry_state
            recovery = {k:v for k,v in retry_state(self.documents(ident)).items() if k != "task_id"}
        keys = (
            "id",
            "request",
            "status",
            "message",
            "action",
            "created_at",
            "updated_at",
            "execution_id",
            "project_id",
            "progress",
        )
        return {
            **{k: copy.deepcopy(job[k]) for k in keys if k in job},
            "can_retry": "retry" in actions,
            "can_continue": "continue" in actions,
            "read_only": not state,
            "latest_completed": state.get("latest_completed"),
            "reused_decision_count": len(job.get("reused_decisions", [])),
            **recovery,
        }

    def public(self, ident):
        job = self.summary(ident)
        state = self.state(ident)
        history = ExecutionHistory(self.documents(ident))
        keys = (
            "status",
            "blocking_questions",
            "critic_pass_count",
            "awaiting_input_reason",
            "review_questions",
            "question_forms",
            "plan",
            "wait_reason",
            "stop_reason",
            "execution_diagnostic",
            "revision",
            "candidate_hash",
            "document_versions",
            "task_results",
        )
        job["state"] = {
            **{k: state[k] for k in keys if k in state and (k != "execution_diagnostic" or state[k])},
            "allowed_actions": self.allowed(ident),
            "saved_answers": saved_answer_dicts(state),
        }
        from backend.services.refinement import public_review
        review = public_review(state)
        if review:
            job["state"]["rubric_review"] = review
        job["execution_graph"], job["session_events"] = (
            history.graph(),
            history.conversation(),
        )
        from backend.services.completed_specs import completed_references

        job["completed_documents"] = [
            {
                "id": Path(n).stem,
                "title": "완료 명세 · " + Path(n).stem[:8],
                "detail_available": True,
                "has_document": True,
                "stage": "completed_document",
            }
            for n in completed_references(state)
        ]
        for name, key in [
            ("draft/approval_candidate_spec.ko.md", "candidate"),
            ("final/FINAL_AGENT_SPEC.md", "final"),
            ("critical/CRITICAL_REPORT.ko.md", "critical"),
        ]:
            text = self.read_text(ident, name)
            if text is not None and (key != "critical" or state.get("critical_report")):
                job[key] = text
        review = self.read_json(ident, "analysis/change_review.json")
        from backend.services.change_review import digest, normalize

        if review and review.get("after_hash") == digest(
            normalize(job.get("candidate", ""))
        ):
            job["change_review"] = review
        return job
