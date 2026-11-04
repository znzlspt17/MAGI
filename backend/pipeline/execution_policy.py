"""실행 선행 조건과 필수 전이의 단일 판정. 모델 호출과 저장은 하지 않는다."""
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from backend.models import parse_issue_list


class StopReason(StrEnum):
    REPAIR_LIMIT = "repair_limit"
    NO_PROGRESS = "no_progress"
    EXECUTION_LIMIT = "execution_limit"
    INVALID_PLAN = "invalid_plan"
    MODEL_BLOCKED = "model_blocked"


class ActionBlockReason(StrEnum):
    PREREQUISITE_MISSING = "prerequisite_missing"
    REVIEW_BUDGET_EXHAUSTED = "review_budget_exhausted"
    REPEATED_WITHOUT_PROGRESS = "repeated_without_progress"


@dataclass(frozen=True)
class ActionEligibility:
    allowed: bool
    reasons: tuple[ActionBlockReason, ...] = ()


@dataclass(frozen=True)
class ExecutionDecision:
    eligibility: dict[str, ActionEligibility]
    required_action: str = ""
    stop_reason: str = ""

    @property
    def allowed_actions(self) -> list[str]:
        return [action for action, result in self.eligibility.items() if result.allowed]

def task_signature(state, action):
    versions = state.get("document_versions", [])
    inputs = [action, state.get("revision"), state.get("requirement_lock_sheet"),
              state.get("structured_issues"), versions[-1]["hash"] if versions else state.get("candidate_hash"),
              state.get("critic_pass_count", 0), state.get("diagnosed_keys", []),
              state.get("confirmed_user_sources"), state.get("knowledge_context")]
    from backend.services.rubric import POLICY_VERSION
    inputs.extend([POLICY_VERSION, state.get("rubric", {}).get("rubric_hash"), state.get("rubric_evaluation")])
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def execution_constraints(state, config):
    recent = [item for item in state.get("task_results", [])[-12:]
              if item.get("segment") == state.get("execution_segment")
              and item.get("status") in {"completed", "no_questions"}]
    repeated = sorted({item["action"] for item in recent if item.get("action")
                       and sum(other.get("action") == item["action"]
                               and other.get("signature") == task_signature(state, item["action"])
                               for other in recent) >= 2})
    return {"remaining_review_passes": max(0, config.max_critic_passes - state.get("critic_pass_count", 0)),
            "repair_limit_reached": state.get("critic_pass_count", 0) >= config.max_critic_passes,
            "no_progress": False,
            "repeated_actions": repeated}


def evaluate_execution(state, config) -> ExecutionDecision:
    done = set(state.get("completed_tasks", []))
    constraints = execution_constraints(state, config)
    stop = ""
    issues = parse_issue_list(state.get("structured_issues", [])) if "review_resolution" in done else []
    unresolved_decisions = any(
        issue.resolution_kind == "user_decision" and issue.status != "resolved" for issue in issues)
    required = ""
    if state.get("blocking_questions") or unresolved_decisions:
        required = "ask_user"
    elif "spec_compile" in done and "checklist_critic" not in done:
        required = "checklist_critic"
    elif "checklist_critic" in done and "review_resolution" not in done:
        required = "review_resolution"
        stop = ""
    elif "review_resolution" in done and state.get("refinement", {}).get("termination"):
        required = "compose_candidate"
        stop = ""
    elif "review_resolution" in done:
        required = "spec_compile"
        stop = ""
    elif stop:
        required = "blocked"
    prerequisites = {
        "ask_user": True, "blocked": bool(stop or state.get("blocking_questions")), "knowledge_search": True,
        "interview": "interview" not in done,
        "project_context": "project_context" not in done,
        "web_research": "web_research" not in done and state.get("web_search_mode") != "off",
        "requirement_lock_stage": bool(state.get("request_type")),
        "spec_compile": "requirement_lock_stage" in done,
        "checklist_critic": "spec_compile" in done,
        "review_resolution": "checklist_critic" in done,
        "compose_candidate": "review_resolution" in done and not unresolved_decisions and not state.get("blocking_questions") and bool(state.get("refinement", {}).get("termination")),
    }
    eligibility = {}
    for action, ready in prerequisites.items():
        reasons = []
        if not ready or ((state.get("blocking_questions") or unresolved_decisions) and action not in {"ask_user", "blocked"}) or (stop and action != "blocked"):
            reasons.append(ActionBlockReason.PREREQUISITE_MISSING)
        if action in {"spec_compile", "checklist_critic"}:
            if constraints["repair_limit_reached"] and action != required:
                reasons.append(ActionBlockReason.REVIEW_BUDGET_EXHAUSTED)
            if constraints["no_progress"]:
                reasons.append(ActionBlockReason.REPEATED_WITHOUT_PROGRESS)
        # 완료 상태를 갱신하거나 승인 대기로 끝나는 필수 전이는 반복 제외보다 우선한다.
        if action in constraints["repeated_actions"] and action != required:
            reasons.append(ActionBlockReason.REPEATED_WITHOUT_PROGRESS)
        eligibility[action] = ActionEligibility(not reasons, tuple(reasons))
    return ExecutionDecision(eligibility, required, stop)


def required_plan(state, decision):
    if not decision.required_action:
        return None
    reasons = {
        "ask_user": "미응답 사용자 결정을 확인합니다.",
        "checklist_critic": "현재 명세를 고정 루브릭으로 평가합니다.",
        "review_resolution": "최신 검토 결과의 해결 방법을 판단합니다.",
        "compose_candidate": "최고점 명세와 남은 결함을 사용자 승인용으로 준비합니다.",
        "spec_compile": "직전 평가의 수정 지시에 따라 명세를 보완합니다.",
        "blocked": "원인 진단 후에도 동일 결함이 반복되었습니다." if decision.stop_reason == StopReason.NO_PROGRESS
                   else "확정 근거로 수정할 문제가 남아 있지만 이번 검토·보완 횟수를 모두 사용했습니다.",
    }
    return {**state.get("plan", {}), "goal": state.get("plan", {}).get("goal") or "명세 검토와 승인 준비",
            "action": decision.required_action, "stop_reason": decision.stop_reason,
            "reason": reasons[decision.required_action]}


@dataclass(frozen=True)
class StopPolicy:
    label: str
    message: str
    allow_questions: bool = True
    create_report: bool = True

_RETRY = " 저장된 결과로 추가 실행할 수 있습니다. 같은 문제가 남을 수 있습니다."
STOP_POLICIES = {
    StopReason.REPAIR_LIMIT: StopPolicy("자동 보완 한계", "{reason} 저장된 결과로 추가 실행을 선택하면 남은 결함의 초안 수정과 재검토를 진행합니다. 추가 의견 없이도 실행할 수 있으며, 같은 문제가 남을 수 있습니다."),
    StopReason.NO_PROGRESS: StopPolicy("진전 없는 반복", "{reason}" + _RETRY),
    StopReason.EXECUTION_LIMIT: StopPolicy("자동 실행 한도", "실행 안전 한도에 도달해 중단했습니다. 저장된 결과에서 추가 실행할 수 있습니다.", False, False),
    StopReason.INVALID_PLAN: StopPolicy("유효한 계획 생성 실패", "실행 가능한 다음 계획을 확정하지 못했습니다." + _RETRY),
    StopReason.MODEL_BLOCKED: StopPolicy("진행 중단", "확인 가능한 상세 중단 진단이 없습니다." + _RETRY),
}

def stop_policy(reason) -> StopPolicy:
    return STOP_POLICIES.get(reason, STOP_POLICIES[StopReason.MODEL_BLOCKED])

def stop_message(policy: StopPolicy, reason: str) -> str:
    prefix = policy.label + " · "
    if reason.startswith(prefix):
        return reason
    message = policy.message.format(reason=reason)
    return message if not policy.allow_questions else prefix + message

def execution_diagnostic(state, config, stop_reason):
    target = {StopReason.REPAIR_LIMIT: "spec_compile", StopReason.NO_PROGRESS: "spec_compile"}.get(stop_reason, "")
    reason = {StopReason.REPAIR_LIMIT: ActionBlockReason.REVIEW_BUDGET_EXHAUSTED,
              StopReason.NO_PROGRESS: ActionBlockReason.REPEATED_WITHOUT_PROGRESS}.get(stop_reason)
    return {"stop_code": str(stop_reason), "target_action": target,
            "block_reasons": [str(reason)] if reason else [],
            "review_pass_count": state.get("critic_pass_count", 0), "review_pass_limit": config.max_critic_passes}
