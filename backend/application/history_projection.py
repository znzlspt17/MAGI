"""실행 기록의 공개 필드 허용 목록과 표시용 요약."""
import copy


def _summary_node(node: dict) -> dict:
    keys = (
        "id",
        "execution_id",
        "action",
        "stage",
        "title",
        "status",
        "started_at",
        "completed_at",
        "duration_ms",
        "summary",
        "issue_counts",
        "has_document",
        "has_issues",
        "detail_available",
        "review_pass",
        "retries",
    )
    return {key: copy.deepcopy(node[key]) for key in keys if key in node}


def _safe_result(value: dict) -> dict:
    allowed = {
        "stop_reason",
        "wait_reason",
        "research",
        "status",
        "blocking_questions",
        "structured_issues",
        "critic_pass_count",
        "request_type",
        "awaiting_input_reason",
        "review_questions",
        "question_forms",
        "resolution_history",
        "diagnosed_keys",
    }
    result = {key: copy.deepcopy(value[key]) for key in allowed if key in value}
    if value.get("status") == "CRITICAL_BLOCKED":
        from backend.services.review_resolution import stop_diagnostic

        result["stop_diagnostic"] = stop_diagnostic(value)
    if isinstance(value.get("plan"), dict):
        result["plan"] = {key: copy.deepcopy(value["plan"][key]) for key in (
            "goal", "tasks", "action", "target", "input_refs", "expected_result", "reason",
            "affected_requirement_ids", "stop_reason",
        ) if key in value["plan"]}
        if isinstance(result["plan"].get("tasks"), list):
            result["plan"]["tasks"] = [
                {key: copy.deepcopy(task[key]) for key in ("id", "title", "status") if key in task}
                for task in result["plan"]["tasks"] if isinstance(task, dict)
            ]
    if isinstance(value.get("diagnostic"), dict):
        result["diagnostic"] = {key: copy.deepcopy(value["diagnostic"][key]) for key in (
            "error_code", "error_stage", "failed_checks", "validation_reason", "validation_section", "validation_index", "validation_field",
        ) if key in value["diagnostic"]}
    return result


def _user_action_result(action: str, value: object) -> dict:
    if action == "generate" and isinstance(value, str):
        return {"request": value}
    if action == "answer" and isinstance(value, list):
        answers = [
            {
                key: item[key]
                for key in ("question_id", "question", "answer")
                if isinstance(item.get(key), str)
            }
            for item in value
            if isinstance(item, dict)
        ]
        return {"answers": answers}
    if action in {"revise", "message", "continue"} and isinstance(value, str):
        return {"feedback": value}
    return {}


def _safe_issues(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    allowed = {
        "issue_id",
        "section",
        "severity",
        "blocking",
        "checklist_id",
        "requirement_id",
        "problem",
        "required_change",
        "evidence",
        "status",
        "resolution_kind",
        "decision_question",
        "decision_answer_id",
        "defect_kind",
        "resolution_reason",
        "missing_information",
        "decision_key",
        "basis_refs",
    }
    return [
        {key: copy.deepcopy(item[key]) for key in allowed if key in item}
        for item in value
        if isinstance(item, dict)
    ]


def _issue_counts(issues: list[dict]) -> dict[str, int]:
    counts = {"blocking": 0, "major": 0, "minor": 0}
    for item in issues:
        severity = item.get("severity")
        if severity in counts and item.get("status", "open") != "resolved":
            counts[severity] += 1
    return counts


def _issue_key(issue: dict) -> tuple[str, str] | None:
    checklist = issue.get("checklist_id")
    requirement = issue.get("requirement_id")
    if not isinstance(checklist, str) or not checklist:
        return None
    return checklist + ":" + str(
        issue.get("decision_key", "")
    ).casefold(), requirement if isinstance(requirement, str) else ""


def _summary(stage: str, result: dict) -> str:
    if result.get("stop_reason") and result.get("wait_reason"):
        return result["wait_reason"]
    if stage == "await_user":
        return (
            "사용자 답변을 기다리고 있습니다."
            if result.get("blocking_questions")
            else "답변을 저장했습니다."
        )
    if stage == "checklist_critic":
        return "검토 결과를 저장했습니다."
    if stage == "web_research" and isinstance(result.get("research"), dict):
        research = result["research"]
        return {
            "skipped": "외부 검색을 생략했습니다.",
            "no_results": "검색 결과 링크가 없습니다.",
            "failed": "외부 검색에 실패했습니다.",
            "links_found": f"검색 결과 링크 {research.get('result_count', 0)}개 발견",
        }.get(research.get("outcome"), "조사 기록을 확인하세요.")
    if stage == "interview":
        return f"확인이 필요한 질문 {len(result.get('blocking_questions') or [])}개를 정리했습니다."
    return "상세 결과 기록 없음"


def _terminal_node_status(status: str) -> str:
    return {
        "NEEDS_USER_INPUT": "waiting",
        "PASS_PENDING_USER_APPROVAL": "waiting_approval",
        "CRITICAL_BLOCKED": "blocked",
        "FINALIZED": "completed",
        "interrupted": "interrupted",
        "error": "failed",
    }.get(status, "completed")


def _terminal_title(status: str) -> str:
    return {
        "NEEDS_USER_INPUT": "요구사항 확인 필요",
        "PASS_PENDING_USER_APPROVAL": "승인 대기",
        "CRITICAL_BLOCKED": "명세 진행 중단",
        "FINALIZED": "승인 완료",
        "error": "실행 오류",
        "interrupted": "실행 중단",
    }.get(status, "실행 완료")

