"""모의 제공자도 실제 모델과 같은 짧은 출처 계약을 사용한다."""

from copy import deepcopy
import json


def planner_result(messages):
    """계획형 엔진 테스트에서 명시적으로 주입하는 결정론적 모델 결과."""
    from backend.models import CompletionResult
    from backend.pipeline.planner import PlannerDecision

    payload = json.loads(
        next(item["content"] for item in messages if item["role"] == "user")
    )
    allowed = payload["allowed_actions"]
    priority = [
        "project_context",
        "interview",
        "requirement_lock_stage",
        "spec_compile",
        "checklist_critic",
        "review_resolution",
        "ask_user",
        "compose_candidate",
        "blocked",
    ]
    done = payload.get("completed_tasks", [])
    action = next(
        (
            item
            for item in priority
            if item in allowed and item not in done and item != "blocked"
        ),
        None,
    )
    if action is None:
        action = "spec_compile" if "spec_compile" in allowed else "blocked"
    if "ask_user" in allowed:
        action = "ask_user"
    if "compose_candidate" in allowed:
        action = "compose_candidate"
    return CompletionResult(
        text="",
        parsed=PlannerDecision(
            goal="검토된 메모 앱 명세 작성",
            tasks=[{"id": action, "title": "필요한 작업 실행", "status": "pending"}],
            action=action,
            target="명세",
            input_refs=["user_request"],
            expected_result="검증된 작업 결과",
            reason="현재 근거와 완료 결과에 따라 필요한 작업입니다.",
            affected_requirement_ids=[],
        ),
    )


def model_context(messages, previous=None):
    context = previous if previous is not None else {}
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            content = "".join(block.get("text", "") for block in content)
        if content.startswith("Canonical context:\n"):
            context.update(json.loads(content.split("\n", 1)[1]))
    return context


def short_sources(value, context):
    aliases = {}
    for ref, item in context.get("sources", {}).items():
        for role in item.get("roles", [item["type"]]):
            if role == "user_answer":
                for question in item.get("questions", [item]):
                    aliases["user_answer:" + question["question_id"]] = ref
            else:
                aliases[role] = ref

    def walk(item, key=""):
        if isinstance(item, list):
            return [walk(child, key) for child in item]
        if isinstance(item, dict):
            return {name: walk(child, name) for name, child in item.items()}
        if key in {"source", "sources", "basis_refs", "conflicting_source"}:
            return aliases.get(item, item)
        return item

    return walk(deepcopy(value))
