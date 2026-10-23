"""모델이 명시한 선택과 근거의 참조 검증."""

from typing import Literal
from hashlib import sha256
from pydantic import BaseModel, ConfigDict


class DecisionTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    text: str
    actor: Literal["user", "llm"]
    rationale: str
    conditions: str
    sources: list[str]
    requirement_ids: list[str]
    reused_node_ids: list[str]


class SpecLink(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str
    section: str
    quote: str
    requirement_ids: list[str]
    decision_ids: list[str]


REQUIREMENT_GROUPS = ("mandatory_requirements", "recommended_requirements",
                      "optional_requirements", "constraints", "non_scope")


class TraceValidationError(ValueError):
    """원문을 포함하지 않는 항목별 검증 진단."""

    def __init__(self, reason, detail):
        super().__init__(reason)
        self.validation_details = [detail]


def source_version(alias, value):
    return alias + ":" + sha256(value.encode()).hexdigest()


def add_source(result, alias, value):
    result[alias] = value
    result[source_version(alias, value)] = value


def action_sources(records):
    result = {}
    for record in records:
        action, payload = record.get("action"), record.get("input")
        if action in {"generate", "revise", "message"} and isinstance(payload, str):
            add_source(result, "user_request" if action == "generate" else "user_feedback", payload)
        elif action == "answer" and isinstance(payload, list):
            for answer in payload:
                if answer.get("question_id") and isinstance(answer.get("answer"), str):
                    add_source(result, "user_answer:" + answer["question_id"], answer["answer"])
    return result


def confirmed_sources(state, artifacts):
    import json
    result = {}
    request = state.get("original_user_request") or state.get("user_request") or artifacts.get("raw/user_request.md", "")
    if request:
        add_source(result, "user_request", request)
    feedback = state.get("revision_feedback") or artifacts.get("raw/web_feedback.md", "")
    if feedback:
        add_source(result, "user_feedback", feedback)
    history = json.loads(artifacts.get("state/execution_history.json", "{}"))
    for node in history.get("nodes", []):
        if node.get("action") == "answer":
            for answer in node.get("result", {}).get("answers", []):
                if answer.get("question_id") and isinstance(answer.get("answer"), str):
                    add_source(result, "user_answer:" + answer["question_id"], answer["answer"])
        elif node.get("action") in {"revise", "message"} and isinstance(node.get("result", {}).get("feedback"), str):
            add_source(result, "user_feedback", node["result"]["feedback"])
    return result


def validate_decisions(decisions, sheet, retrieved=(), feedback="", request="", confirmed=None, previous=()):
    requirements = {item["id"] for group in REQUIREMENT_GROUPS for item in sheet.get(group, [])}
    user_sources = {"user_request": request}
    if feedback:
        user_sources["user_feedback"] = feedback
    user_sources.update({"user_answer:" + item["question_id"]: item["answer"] for item in sheet.get("user_answers", [])})
    ids = set()
    prior = {item["id"]: item for item in previous}
    for raw in decisions:
        decision = DecisionTrace.model_validate(raw).model_dump()
        if not decision["id"].strip() or decision["id"] in ids or not decision["text"].strip():
            raise ValueError("결정 ID가 비어 있거나 중복되었습니다.")
        ids.add(decision["id"])
        if not set(decision["requirement_ids"]) <= requirements:
            raise ValueError("결정이 존재하지 않는 요구사항을 참조합니다.")
        permitted = set(retrieved)
        if prior.get(decision["id"]) == decision:
            # 이전 선택을 그대로 보존하는 것은 과거 출처의 새로운 채택과 구분한다.
            permitted.update(decision["reused_node_ids"])
        from backend.services.project_decisions import CURRENT_REUSE, source_ref
        available_sources = user_sources.keys() | (confirmed or {}).keys() | {source_ref(item) for item in CURRENT_REUSE.get()}
        if not set(decision["sources"]) <= available_sources or not set(decision["reused_node_ids"]) <= permitted:
            raise ValueError("결정 출처를 확인할 수 없습니다.")
        if decision["actor"] == "user":
            # 사용자가 실제 작성한 원문만 사용자 확정 결정으로 분류한다.
            actual = user_sources if confirmed is None else confirmed
            if decision["reused_node_ids"] or not decision["sources"] or not any(
                decision["text"] in actual.get(source, "") for source in decision["sources"]
            ):
                raise ValueError("사용자 결정은 실제 사용자 원문으로 확인되어야 합니다.")
        if decision["reused_node_ids"] and not decision["rationale"].strip():
            raise ValueError("재사용 결정에 적용 근거가 필요합니다.")


def validate_links(links, decisions, sheet, sections):
    requirements = {item["id"] for group in REQUIREMENT_GROUPS for item in sheet.get(group, [])}
    known_decisions = {item["id"] for item in decisions}
    item_ids = set()
    for index, raw in enumerate(links):
        link = SpecLink.model_validate(raw).model_dump()
        path = f"spec_links[{index}]"
        if not link["item_id"].strip() or link["item_id"] in item_ids:
            raise TraceValidationError("명세 항목 ID가 비어 있거나 중복되었습니다.",
                                       path + ".item_id: must be nonempty and unique.")
        item_ids.add(link["item_id"])
        if link["section"] not in sections or not isinstance(sections[link["section"]], str):
            raise TraceValidationError("명세 항목의 섹션과 인용을 확인할 수 없습니다.",
                path + ".section: must be an exact prose response field name, e.g. architecture; never a Markdown heading, decisions or spec_links.")
        if not link["quote"].strip() or link["quote"] not in sections[link["section"]]:
            raise TraceValidationError("명세 항목의 섹션과 인용을 확인할 수 없습니다.",
                path + ".quote: must be an exact nonempty substring of its named section. Keep the quote in the final assembled document; use implementation sections for links to locked requirements.")
        if not set(link["requirement_ids"]) <= requirements:
            raise TraceValidationError("명세 항목이 존재하지 않는 결정을 참조합니다.",
                path + ".requirement_ids: reference only requirement IDs present in the supplied lock sheet.")
        if not set(link["decision_ids"]) <= known_decisions:
            raise TraceValidationError("명세 항목이 존재하지 않는 결정을 참조합니다.",
                path + ".decision_ids: reference only supplied lock decisions or decisions declared in this response.")
