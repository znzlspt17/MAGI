"""확정 근거와 검토 제안을 대조해 다음 행동을 결정한다."""

import hashlib
import re

from backend.errors import ReviewValidationError
from backend.infrastructure.output_language import has_hangul, prose
from backend.knowledge.trace import REQUIREMENT_GROUPS
from backend.models import ReviewResolutionResponse


def decision_identity(issue):
    return (issue.requirement_id or "structure") + ":" + issue.decision_key.casefold()


def defect_identity(issue):
    return decision_identity(issue) + ":" + issue.checklist_id.casefold()


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def confirmed_basis(state, sheet):
    basis = {item["id"]: item["text"] for group in REQUIREMENT_GROUPS for item in sheet.get(group, [])}
    basis["user_request"] = state.get("original_user_request") or state.get("user_request", "")
    basis.update(state.get("confirmed_user_sources", {}))
    from backend.services.project_decisions import source_ref
    basis.update({source_ref(item): item["text"] for item in state.get("reused_decisions", [])})
    if state.get("revision_feedback"):
        basis["user_feedback"] = state["revision_feedback"]
    return basis


def validate_resolutions(packet, issues, basis, records, state):
    if not isinstance(packet, ReviewResolutionResponse):
        raise ReviewValidationError(["Return the complete review resolution schema."], stage="review_resolution", check="resolution_schema")
    by_id = {issue.issue_id: issue for issue in issues}
    if len(packet.resolutions) != len(by_id) or {item.issue_id for item in packet.resolutions} != set(by_id):
        raise ReviewValidationError(["Resolve each supplied issue exactly once without adding issues."], stage="review_resolution", check="resolution_coverage")
    reconfirm = set()
    for item in packet.resolutions:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,100}", item.decision_key):
            raise ReviewValidationError(["Use a stable English decision topic key."], stage="review_resolution", check="decision_key")
        for name in ("resolution_reason", "required_change"):
            if not has_hangul(prose(getattr(item, name))):
                raise ReviewValidationError(["Resolution reason and required change must explain the action in Korean."], stage="review_resolution", check="resolution_language")
        if not item.basis_refs or not set(item.basis_refs) <= basis.keys():
            raise ReviewValidationError(["Cite only supplied confirmed product requirement IDs or actual user source references."], stage="review_resolution", check="resolution_basis")
        issue = by_id[item.issue_id]
        # 검토기와 해결 판단기가 서로 다른 주제로 바꿔 반복 추적을 우회하지 못한다.
        if item.decision_key.casefold() != issue.decision_key.casefold():
            raise ReviewValidationError(["Preserve the supplied stable decision_key; change classification rather than identity."], stage="review_resolution", check="decision_key")
        if item.resolution_kind == "user_decision":
            if item.defect_kind not in {"requirements_gap", "confirmed_conflict"} or item.impact == "none" or not item.missing_information.strip() or not item.decision_question or not has_hangul(prose(item.decision_question)):
                raise ReviewValidationError(["Ask only for a missing material product decision, explaining missing information and impact in Korean."], stage="review_resolution", check="resolution_question")
        elif item.decision_question is not None or item.decision_form is not None or item.missing_information.strip():
            raise ReviewValidationError(["Auto fixes require null decision_question and empty missing_information; cite confirmed basis and a concrete fix."], stage="review_resolution", check="resolution_auto_fix")
        if item.conflicting_source is not None:
            key = decision_identity(issue)
            record = next((record for record in reversed(records) if record["decision_key"] == key), None)
            feedback = state.get("revision_feedback", "")
            if (item.resolution_kind != "user_decision" or item.defect_kind != "confirmed_conflict"
                    or item.conflicting_source != "user_feedback" or "user_feedback" not in item.basis_refs
                    or not feedback or record is None or record.get("feedback_hash") == text_hash(feedback)):
                raise ReviewValidationError(["Reconfirmation requires a new, cited user_feedback conflicting with an existing answered decision."], stage="review_resolution", check="resolution_reconfirmation")
            answers = state.get("confirmed_user_sources", {})
            if "user_answer:" + record["question_id"] not in answers:
                raise ReviewValidationError(["Only previously answered decisions can be reconfirmed."], stage="review_resolution", check="resolution_reconfirmation")
            reconfirm.add(key)
        issue.defect_kind = item.defect_kind
        issue.resolution_kind = item.resolution_kind
        issue.resolution_reason = item.resolution_reason
        issue.missing_information = item.missing_information
        issue.decision_form = item.decision_form.model_dump() if item.decision_form else None
        issue.decision_question = item.decision_question
        issue.required_change = item.required_change
        issue.basis_refs = list(item.basis_refs)
    return reconfirm


def failure_report(state):
    lines = ["# 명세 보완 실패", "", "자동 보완으로 남은 결함을 해결하지 못했습니다. 사용자 요구사항 부족으로 판정한 결과가 아닙니다.", ""]
    for attempt in state.get("resolution_history", []):
        lines += [f"## 검토 {attempt['review_round']} · {attempt['draft_hash'][:12]}",
                  "원인 진단: " + ("실행" if attempt.get("diagnosed_keys") else "없음")]
        for issue in attempt["issues"]:
            lines += [f"- [{issue['decision_key']}] {issue['problem']}",
                      f"  - 판단: {issue['resolution_reason']}", f"  - 시도한 보완: {issue['required_change']}",
                      "  - 근거: " + ", ".join(issue.get("basis_refs", []))]
    lines += ["", "## 남은 결함"]
    for issue in state.get("structured_issues", []):
        if issue.get("status") != "resolved" and (issue.get("severity") in {"blocking", "major"} or issue.get("decision_answer_id")):
            lines.append(f"- [{issue['decision_key']}] {issue['problem']}")
    lines += ["", "종료 이유: " + ("원인 진단 후에도 동일 결함이 남았습니다." if state.get("resolution_stop") else "설정된 검토·보완 횟수를 모두 사용했습니다.")]
    return "\n".join(lines) + "\n"
