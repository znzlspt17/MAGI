"""작업별 실행 이력의 안전한 저장과 공개용 요약 생성."""

from __future__ import annotations

import copy
from protocol.logging import get_logger
from datetime import UTC, datetime
from uuid import uuid4

from backend.infrastructure.usage import provider_usage_summary


LOGGER = get_logger("backend.server")
_MAX_SUMMARY = 600
_STAGES = {
    "generate",
    "answer",
    "revise",
    "approve",
    "retry",
    "message",
    "planner",
    "knowledge_search",
    "project_context",
    "web_research",
    "interview",
    "await_user",
    "requirement_lock",
    "spec_compile",
    "checklist_critic",
    "review_resolution",
    "compose_candidate",
    "critical_report",
}
_TITLES = {
    "message": "수정 의견",
    "planner": "작업 계획",
    "knowledge_search": "기존 근거 확인",
    "generate": "요청 접수",
    "answer": "답변 제출",
    "revise": "수정 의견 제출",
    "approve": "승인",
    "retry": "다시 시도",
    "project_context": "요청 분석",
    "web_research": "조사",
    "interview": "요구사항 확인",
    "await_user": "요구사항 확인 필요",
    "requirement_lock": "요구사항 확정",
    "spec_compile": "명세 생성",
    "checklist_critic": "명세 검토",
    "review_resolution": "해결 방법 판단",
    "compose_candidate": "승인 후보 준비",
    "critical_report": "명세 진행 중단 보고",
    "workflow": "실행 흐름",
}


class ExecutionHistory:
    """대화와 타임라인이 공유하는 업무 이력이다."""

    def __init__(self, documents):
        self.documents = documents

    def conversation(self):
        data = self._load(read_only=True) or {"nodes": [], "executions": []}
        result = []
        for execution in data["executions"]:
            nodes = [
                n for n in data["nodes"] if n.get("execution_id") == execution["id"]
            ]
            user = next(
                (
                    n
                    for n in nodes
                    if n.get("action")
                    in {
                        "generate",
                        "answer",
                        "revise",
                        "approve",
                        "message",
                        "continue",
                    }
                ),
                {},
            )
            payload = user.get("result", {})
            document = next((n for n in reversed(nodes) if n.get("has_document")), {})
            questions = next(
                (
                    n.get("result", {}).get("blocking_questions")
                    for n in reversed(nodes)
                    if isinstance(n.get("result", {}).get("blocking_questions"), list)
                ),
                [],
            )
            result.append(
                {
                    "id": execution["id"],
                    "action": execution["action"],
                    **(
                        {"retry_of": execution["retry_of"]}
                        if execution.get("retry_of")
                        else {}
                    ),
                    "input": {
                        k: payload[k]
                        for k in ("request", "feedback", "answers")
                        if k in payload
                    },
                    "status": execution.get("status", "running"),
                    "started_at": execution.get("started_at"),
                    "document_step_id": document.get("id"),
                    "questions": questions,
                    "summary": nodes[-1].get("summary", "") if nodes else "",
                }
            )
        return result

    def start_execution(
        self, action: str, execution_id: str | None = None, *, input_data: object = None
    ) -> str:
        execution_id = execution_id or uuid4().hex
        data = self._load()
        if any(item.get("id") == execution_id for item in data["executions"]):
            return execution_id
        node = _node(
            action, execution_id, "completed", summary="사용자 작업을 접수했습니다."
        )
        user_result = _user_action_result(action, input_data)
        if user_result:
            node["result"] = user_result
        data["nodes"].append(node)
        data["executions"].append(
            {"id": execution_id, "action": action, "started_at": _now()}
        )
        if (
            action == "retry"
            and isinstance(input_data, dict)
            and isinstance(input_data.get("retry_of"), str)
        ):
            data["executions"][-1]["retry_of"] = input_data["retry_of"]
            node["summary"] = "저장된 작업을 다시 시도합니다."
        self._save(data)
        return execution_id

    def stage(
        self, execution_id: str, stage: str, state: str, *, result: dict | None = None
    ) -> None:
        if stage not in _STAGES or state not in {
            "started",
            "retrying",
            "completed",
            "failed",
        }:
            return
        data = self._load()
        nodes = data["nodes"]
        current = next(
            (
                item
                for item in reversed(nodes)
                if item.get("execution_id") == execution_id
                and item.get("stage") == stage
                and item.get("status") == "running"
            ),
            None,
        )
        if state == "retrying":
            if current is not None and isinstance(result, dict):
                attempt = result.get("retry_attempt")
                if type(attempt) is int and 1 <= attempt <= 3:
                    message = f"재시도 중… ({attempt}/3)"
                    current["summary"] = message
                    current.setdefault("retries", []).append(
                        {"attempt": attempt, "message": message, "started_at": _now()}
                    )
        elif state == "started":
            if current is None:
                node = _node(stage, execution_id, "running")
                node["usage_start"] = _usage_attempt_count(self.documents)
                nodes.append(node)
        elif current is not None:
            current["status"] = "completed" if state == "completed" else "failed"
            if current.get("retries"):
                current["summary"] = (
                    "재시도를 완료했습니다."
                    if state == "completed"
                    else "재시도 중 오류로 중단했습니다."
                )
            current["completed_at"] = _now()
            current["duration_ms"] = _duration(
                current.get("started_at"), current["completed_at"]
            )
            if result:
                current["result"] = _safe_result(result)
                current["summary"] = _summary(stage, result)
            current["usage"] = _usage_since(self.documents, current.get("usage_start"))
        else:
            node = _node(
                stage, execution_id, "completed" if state == "completed" else "failed"
            )
            node["started_at"] = None
            node["completed_at"] = _now()
            if result:
                node["result"] = _safe_result(result)
                node["summary"] = _summary(stage, result)
            nodes.append(node)
        self._save(data)

    def terminal(
        self,
        execution_id: str,
        status: str,
        message: str = "",
        *,
        result: dict | None = None,
    ) -> None:
        data = self._load()
        for item in reversed(data["nodes"]):
            if (
                item.get("execution_id") == execution_id
                and item.get("status") == "running"
            ):
                item["status"] = "interrupted" if status == "interrupted" else "failed"
                item["completed_at"] = _now()
                item["duration_ms"] = _duration(
                    item.get("started_at"), item["completed_at"]
                )
        for execution in reversed(data["executions"]):
            if execution.get("id") == execution_id:
                execution["status"] = status
                execution["completed_at"] = _now()
                break
        if status == "NEEDS_USER_INPUT":
            candidates = [
                item
                for item in reversed(data["nodes"])
                if item.get("execution_id") == execution_id
            ]
            target = next(
                (item for item in candidates if item.get("stage") == "await_user"), None
            )
            if target is None:
                target = next(
                    (item for item in candidates if _is_wait_terminal(item)), None
                )
            if target is not None:
                target["status"] = "waiting"
                target["summary"] = message or "사용자 답변을 기다리고 있습니다."
                target["result"] = {
                    **target.get("result", {}),
                    "status": status,
                    **_safe_result(result or {}),
                }
                self._save(data)
                return
        if message or status == "NEEDS_USER_INPUT":
            terminal = _node(
                "workflow", execution_id, _terminal_node_status(status), summary=message
            )
            terminal["title"] = _terminal_title(status)
            source = next(
                (
                    item
                    for item in reversed(data["nodes"])
                    if item.get("execution_id") == execution_id
                    and item.get("stage") != "workflow"
                    and item.get("status")
                    in {"completed", "blocked", "waiting_approval"}
                ),
                None,
            )
            if isinstance(source, dict):
                for key in (
                    "detail",
                    "result",
                    "issue_counts",
                    "has_document",
                    "has_issues",
                ):
                    if key in source:
                        terminal[key] = copy.deepcopy(source[key])
            if result:
                terminal["result"] = {
                    **terminal.get("result", {}),
                    **_safe_result(result),
                }
            data["nodes"].append(terminal)
        self._save(data)

    def capture(self, execution_id: str, stage: str, *, state=None) -> None:
        """완료 시점 산출물을 복사해 이후 초안 덮어쓰기를 막는다."""
        data = self._load()
        node = next(
            (
                item
                for item in reversed(data["nodes"])
                if item.get("execution_id") == execution_id
                and item.get("stage") == stage
            ),
            None,
        )
        if node is None:
            return
        detail = node.setdefault("detail", {})
        state = state or self.documents.state or {}
        root = self.documents
        if state.get("reused_decisions"):
            detail["reused_decisions"] = copy.deepcopy(state["reused_decisions"])
        saved_plan = node.get("result", {}).get("plan")
        if stage == "planner" and isinstance(saved_plan or state.get("plan"), dict):
            # 공개 판단 결과만 보관하고 모델 메시지나 내부 실행 상태는 복사하지 않는다.
            plan = saved_plan or state["plan"]
            detail.setdefault("result", {})["plan"] = _safe_result({"plan": plan})["plan"]
            node["summary"] = str(plan.get("reason") or "작업 계획을 저장했습니다.")[:_MAX_SUMMARY]
        elif stage == "await_user":
            node["status"] = "waiting"
            node["summary"] = "사용자 답변을 기다리고 있습니다."
        elif stage == "spec_compile":
            self._copy_document(
                "draft/approval_candidate_spec.en.md", detail, node, "draft"
            )
        elif stage in {"checklist_critic", "review_resolution"}:
            self._copy_document(
                "draft/approval_candidate_spec.en.md", detail, node, "draft"
            )
            issues = _read_json(
                root,
                "review/resolution.json"
                if stage == "review_resolution"
                else "review/checklist_issues.json",
            )
            if stage == "review_resolution" and isinstance(issues, dict):
                detail.setdefault("result", {}).update(
                    {
                        key: issues[key]
                        for key in ("draft_hash", "diagnosed_keys", "action")
                        if key in issues
                    }
                )
            if isinstance(issues, dict):
                detail["issues"] = _safe_issues(issues.get("issues"))
                previous = self._previous_review_issues(data["nodes"], node["id"])
                current_keys = {_issue_key(item) for item in detail["issues"]}
                for item in detail["issues"]:
                    item["lifecycle"] = (
                        "persistent" if _issue_key(item) in previous else "new"
                    )
                detail["resolved_issues"] = [
                    {**copy.deepcopy(item), "lifecycle": "resolved"}
                    for key, item in previous.items()
                    if key not in current_keys
                ]
                node["issue_counts"] = _issue_counts(detail["issues"])
                node["has_issues"] = bool(detail["issues"] or detail["resolved_issues"])
                node["review_pass"] = (
                    issues.get("pass") if isinstance(issues.get("pass"), int) else None
                )
                if stage == "review_resolution" and any(
                    item.get("resolution_kind") == "user_decision"
                    and item.get("status") != "resolved"
                    for item in detail["issues"]
                ):
                    node["status"] = "waiting"
                    node["summary"] = (
                        "명세 검토 중 사용자 결정이 필요한 항목이 있습니다."
                    )
                elif node["issue_counts"]["blocking"] or node["issue_counts"]["major"]:
                    node["status"] = "needs_revision"
                    node["summary"] = "보완이 필요한 검토 항목이 있습니다."
                else:
                    node["status"] = "completed"
                    node["summary"] = "검토를 통과했습니다."
        elif stage == "requirement_lock":
            sheet = _read_json(root, "analysis/requirement_lock_sheet.json")
            if isinstance(sheet, dict):
                detail["requirements"] = {
                    key: copy.deepcopy(sheet.get(key, []))
                    for key in (
                        "mandatory_requirements",
                        "recommended_requirements",
                        "optional_requirements",
                        "constraints",
                    )
                    if isinstance(sheet.get(key), list)
                }
        elif stage == "compose_candidate":
            self._copy_document(
                "draft/approval_candidate_spec.en.md", detail, node, "candidate"
            )
            review = _read_json(root, "analysis/change_review.json")
            from backend.services.change_review import digest, normalize

            content = self._read_document(detail.get("document", {}))
            if isinstance(review, dict) and review.get("after_hash") == digest(
                normalize(content)
            ):
                detail["change_review"] = copy.deepcopy(review)
            pointer = _read_json(root, "state/candidate_snapshot.json")
            if isinstance(pointer, dict):
                detail["review_snapshot_id"] = pointer.get("id")
            node["status"] = "waiting_approval"
            node["summary"] = "사용자 승인을 기다리고 있습니다."
        elif stage == "critical_report":
            self._copy_document(
                "critical/FAILED_AGENT_SPEC_DRAFT.en.md", detail, node, "draft"
            )
            try:
                report = root.read_text("critical/CRITICAL_REPORT.ko.md")
            except (OSError, UnicodeError):
                report = ""
            if report:
                detail.setdefault("result", {})["report"] = report
            review = self._latest_review_detail(data["nodes"], node["id"])
            if review:
                detail["issues"] = copy.deepcopy(review.get("issues", []))
                detail["resolved_issues"] = copy.deepcopy(
                    review.get("resolved_issues", [])
                )
                node["issue_counts"] = _issue_counts(detail["issues"])
                node["has_issues"] = bool(detail["issues"] or detail["resolved_issues"])
            node["status"] = "blocked"
            node["summary"] = "남은 결함과 자동 보완 실패 원인을 확인하세요."
        elif stage == "approve":
            self._copy_document("final/FINAL_AGENT_SPEC.md", detail, node, "final")
            saved = root.state
            completed = (
                (saved.get("latest_completed") or {}) if isinstance(saved, dict) else {}
            )
            if isinstance(completed.get("id"), str) and detail.get("document"):
                detail["document"]["completed_id"] = completed["id"]
            pointer = _read_json(root, "state/candidate_snapshot.json")
            if isinstance(pointer, dict):
                detail["review_snapshot_id"] = pointer.get("id")
        self._save(data)

    @staticmethod
    def _previous_review_issues(
        nodes: list[dict], node_id: str
    ) -> dict[tuple[str, str], dict]:
        for item in reversed(nodes):
            if item.get("id") == node_id:
                continue
            detail = item.get("detail")
            current_stage = next(
                (node["stage"] for node in nodes if node.get("id") == node_id),
                "checklist_critic",
            )
            if item.get("stage") != current_stage or not isinstance(detail, dict):
                continue
            issues = detail.get("issues")
            if isinstance(issues, list):
                return {
                    _issue_key(issue): issue
                    for issue in issues
                    if isinstance(issue, dict) and _issue_key(issue) is not None
                }
        return {}

    @staticmethod
    def _latest_review_detail(nodes: list[dict], node_id: str) -> dict:
        for item in reversed(nodes):
            if item.get("id") == node_id:
                continue
            detail = item.get("detail")
            if item.get("stage") in {
                "checklist_critic",
                "review_resolution",
            } and isinstance(detail, dict):
                return detail
        return {}

    def graph(self) -> dict:
        data = self._load(read_only=True)
        if data is None:
            return {"version": 1, "nodes": [], "recording_incomplete": True}
        nodes = data["nodes"]
        return {
            "version": 1,
            "nodes": [_summary_node(item) for item in nodes],
            "recording_incomplete": bool(data.get("recording_incomplete")),
        }

    def detail(self, step_id: str) -> dict | None:
        data = self._load(read_only=True)
        if data is None:
            return None
        nodes = data["nodes"]
        node = next((item for item in nodes if item.get("id") == step_id), None)
        if node is None:
            return None
        result = copy.deepcopy(node.get("result") or {})
        detail = node.get("detail") if isinstance(node.get("detail"), dict) else {}
        if "issues" in detail:
            result["issues"] = copy.deepcopy(detail["issues"])
        if "resolved_issues" in detail:
            result["resolved_issues"] = copy.deepcopy(detail["resolved_issues"])
        if "requirements" in detail:
            result["requirements"] = copy.deepcopy(detail["requirements"])
        if isinstance(detail.get("result"), dict):
            result.update(copy.deepcopy(detail["result"]))
        payload = _summary_node(node)
        payload["result"] = result
        if isinstance(detail.get("change_review"), dict):
            payload["change_review"] = copy.deepcopy(detail["change_review"])
        if isinstance(detail.get("review_snapshot_id"), str):
            payload["review_snapshot_id"] = detail["review_snapshot_id"]
        if isinstance(result.get("research"), dict):
            payload["research"] = copy.deepcopy(result["research"])
        if isinstance(node.get("usage"), dict):
            payload["usage"] = copy.deepcopy(node["usage"])
        if isinstance(detail.get("document"), dict):
            document = copy.deepcopy(detail["document"])
            content = self._read_document(document)
            if content is None:
                payload["recording_incomplete"] = True
            else:
                document["content"] = content
                payload["document"] = document
        return payload

    def interrupt_running(self) -> None:
        data = self._load(read_only=True)
        if data is None:
            return
        changed = False
        for node in data["nodes"]:
            if node.get("status") == "running":
                node["status"] = "interrupted"
                node["completed_at"] = None
                node["duration_ms"] = None
                changed = True
        if changed:
            self._save(data)

    def interrupt_execution(self, execution_id: object) -> None:
        if not isinstance(execution_id, str):
            return
        data = self._load(read_only=True)
        if data is None:
            return
        for execution in data["executions"]:
            if execution.get("id") == execution_id:
                execution["status"] = "interrupted"
                execution.pop("completed_at", None)
        for node in data["nodes"]:
            if (
                node.get("execution_id") == execution_id
                and node.get("status") == "running"
            ):
                node["status"] = "interrupted"
                node["completed_at"] = None
                node["duration_ms"] = None
        self._save(data)

    def _copy_document(self, name, detail, node, kind):
        if not self.documents.exists(name):
            node["detail_available"] = False
            return
        detail["document"] = {
            "version_id": self.documents.reference(name),
            "filename": name.rsplit("/", 1)[-1],
            "kind": kind,
        }
        node["has_document"] = True

    def _read_document(self, document):
        ident = document.get("version_id")
        return self.documents.version(ident) if ident else None

    def _load(self, *, read_only=False):
        with self.documents.store.transaction(mode="read") as conn:
            nodes = conn.execute(
                "SELECT data FROM execution_events WHERE job_id=%s ORDER BY sequence",
                (self.documents.job_id,),
            ).fetchall()
            executions = conn.execute(
                "SELECT id,data,timeline FROM executions WHERE job_id=%s ORDER BY sequence",
                (self.documents.job_id,),
            ).fetchall()
        records = [{**r["data"], **r["timeline"], "id": r["id"]} for r in executions]
        inputs = {
            r["id"]: _user_action_result(r.get("action"), r.get("input"))
            for r in records
        }
        projected = [
            {
                **r["data"],
                **(
                    {"result": inputs.get(r["data"]["execution_id"], {})}
                    if r["data"].get("action")
                    else {}
                ),
            }
            for r in nodes
        ]
        return {
            "version": 1,
            "nodes": projected,
            "executions": records,
            "recording_incomplete": False,
        }

    def _save(self, data):
        store = self.documents.store
        with store.transaction() as conn:
            for execution in data["executions"]:
                timeline = {
                    k: v
                    for k, v in execution.items()
                    if k not in {"input", "id", "action", "stage"}
                }
                conn.execute(
                    "UPDATE executions SET timeline=%s WHERE id=%s AND job_id=%s",
                    (store._json(timeline), execution["id"], self.documents.job_id),
                )
            for node in data["nodes"]:
                node = copy.deepcopy(node)
                if node.get("action"):
                    node.pop("result", None)
                conn.execute(
                    "INSERT INTO execution_events(id,job_id,execution_id,data) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data WHERE execution_events.data IS DISTINCT FROM EXCLUDED.data",
                    (
                        node["id"],
                        self.documents.job_id,
                        node["execution_id"],
                        store._json(node),
                    ),
                )


def _is_wait_terminal(node: dict) -> bool:
    return node.get("stage") == "workflow" and node.get("status") == "waiting"


def _node(stage: str, execution_id: str, status: str, *, summary: str = "") -> dict:
    now = _now()
    return {
        "id": uuid4().hex,
        "execution_id": execution_id,
        "action": stage
        if stage in {"generate", "answer", "revise", "approve", "message", "continue"}
        else "",
        "stage": stage,
        "title": _TITLES.get(stage, stage),
        "status": status,
        "started_at": now,
        "completed_at": None,
        "duration_ms": None,
        "summary": summary,
        "issue_counts": {"blocking": 0, "major": 0, "minor": 0},
        "has_document": False,
        "has_issues": False,
        "detail_available": True,
    }


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


def _duration(started_at: object, completed_at: object) -> int | None:
    try:
        return max(
            0,
            int(
                (
                    datetime.fromisoformat(str(completed_at))
                    - datetime.fromisoformat(str(started_at))
                ).total_seconds()
                * 1000
            ),
        )
    except (TypeError, ValueError):
        return None


def _read_json(documents, name):
    return documents.read_json(name) if documents.exists(name) else None


def _usage_attempt_count(documents):
    value = documents.usage()
    return len(value.get("attempts", []))


def _usage_since(documents, start):
    value = documents.usage()
    if not isinstance(start, int):
        return None
    return provider_usage_summary(
        {"attempts": value.get("attempts", [])[start:], "recording_incomplete": False}
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
