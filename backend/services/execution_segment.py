"""사용자 입력에 따른 실행 구간 상태 전환. 저장과 모델 호출은 하지 않는다."""
from backend.models import WorkflowState
from typing import TypedDict


class ReviewBudget(TypedDict):
    critic_pass_count: int
    resolution_stop: bool
    diagnosed_keys: list[str]


def fresh_review_budget() -> ReviewBudget:
    """사용자 입력 또는 명시적 재시도가 시작한 보완 구간의 초기 예산."""
    return {"critic_pass_count": 0, "resolution_stop": False, "diagnosed_keys": []}


def prepare_segment(state: WorkflowState) -> WorkflowState:
    action = state.get("pending_input", {}).get("action", "generate")
    done = list(state.get("completed_tasks", []))
    revision = state.get("revision", 0)
    if action in {"answer", "revise", "message"}:
        revision += 1
        # 변경 영향을 확정할 수 없는 입력은 생성물을 보수적으로 재검증한다.
        preserved = {"project_context", "knowledge_search", "web_research"}
        if action == "answer" and state.get("pending_input", {}).get("origin_reason") == "review":
            preserved.add("interview")
        done = [name for name in done if name in preserved]
    result: WorkflowState = {"workflow_schema": 1, "revision": revision, "completed_tasks": done,
              "allowed_actions": [], "pending_input": {},
              "execution_constraints": {}, "execution_diagnostic": {},
              "execution_segment": state.get("execution_segment", 0) + 1,
              "wait_reason": "", "stop_reason": ""}
    if action == "rubric_recovery":
        # 2026-11-05: 같은 입력의 복구는 사용자 재시도를 포함해 한 번만 허용한다.
        from backend.services.rubric import invalid
        pending = state.get("pending_input", {})
        fingerprint, reason = pending.get("fingerprint"), pending.get("reason")
        history = state.get("rubric_recoveries", [])
        if not isinstance(fingerprint, str) or fingerprint in history:
            raise invalid("rubric_stale", stage="checklist_critic", reason="recovery_exhausted")
        rebuild = reason == "rubric_input_changed"
        invalidated = {"checklist_critic", "review_resolution", "compose_candidate"}
        if rebuild:
            invalidated.add("spec_compile")
        result["completed_tasks"] = [name for name in done if name not in invalidated]
        result["rubric_recoveries"] = [*history, fingerprint]
        result["rubric_recovery_pending"] = rebuild
        result["rubric"] = state.get("rubric", {})
        result["rubric_evaluation"] = {}
        result["rubric_summary"] = {}
        result["refinement"] = {}
        result["approval_acceptance"] = {}
        result["structured_issues"] = []
        result["resolution_history"] = []
        result.update(fresh_review_budget())
        return result
    if action in {"answer", "revise", "message"}:
        result.update(fresh_review_budget())
        result["refinement"] = {}
        result["approval_acceptance"] = {}
    if action == "retry" and state.get("refinement", {}).get("termination") and state["refinement"].get("selected"):
        previous = state["refinement"]
        result.update(fresh_review_budget())
        result["refinement"] = {**previous, "round": 0, "stale": 0,
            "cycle": previous["cycle"] + 1, "termination": "", "selected": False, "last_token": ""}
        result["approval_acceptance"] = {}
        result["completed_tasks"] = [name for name in done if name not in {
            "spec_compile", "checklist_critic", "review_resolution", "compose_candidate"}]
    if action in {"generate", "answer", "revise", "message", "retry"} and state.get("requirement_lock_sheet"):
        from backend.models import RequirementLockSheet
        from backend.services.rubric import current_record
        sheet = RequirementLockSheet.from_dict(state["requirement_lock_sheet"])
        if not current_record(state.get("rubric", {}), sheet, state):
            # 구형 작업의 완료 표시는 새 정책의 생성·검토를 대신하지 못한다.
            result["completed_tasks"] = [name for name in done if name not in {
                "spec_compile", "checklist_critic", "review_resolution", "compose_candidate"}]
            result["rubric_evaluation"] = {}
            result["rubric_summary"] = {}
            result["refinement"] = {}
            result.update(fresh_review_budget())
    if action in {"answer", "revise", "message"}:
        result.update({"candidate_hash": "", "user_approval_status": "PENDING", "critical_report": None})
        reused = [{"action": name, "revision": revision, "status": "reused",
                   "reason": "새 입력의 영향을 받지 않는 이전 자료를 재사용합니다."} for name in done]
        result["task_results"] = [*state.get("task_results", []), *reused]
    return result
