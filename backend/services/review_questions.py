"""검토 지적을 기존 답변과 연결하고 중복 없는 결정 질문으로 묶는다."""

from copy import deepcopy
from hashlib import sha256
from typing import Any

from backend.errors import ReviewValidationError
from backend.infrastructure.output_language import has_hangul, prose
from backend.services.saved_answers import saved_answers
from backend.models import IssuePacket, WorkflowState, parse_issue_list
from backend.services.review_resolution import decision_identity, text_hash


def collect_review_questions(
    issues: list[IssuePacket], state: WorkflowState, review_round: int, *, reconfirm_keys=()
) -> tuple[list[dict[str, Any]], list[str]]:
    """동일 결정 키는 한 번만 묻고, 확인된 답변은 자동 보완에 사용한다."""
    records = deepcopy(state.get("review_questions", []))
    by_key = {item["decision_key"]: item for item in records}
    answers = saved_answers(state)
    by_id = {item.question_id: item for item in answers}
    previous = {decision_identity(item): item
                for item in parse_issue_list(state.get("structured_issues", []))}
    pending = []
    pending_ids = set()
    for issue in issues:
        if issue.status == "resolved":
            continue
        if issue.resolution_kind != "user_decision":
            prior = previous.get(decision_identity(issue))
            if prior:
                record = by_key.get(decision_identity(issue))
                answer = by_id.get(prior.decision_answer_id) or (by_id.get(record["question_id"]) if record else None)
                if answer:
                    # 같은 지적이 남아 있으면 분류나 심각도가 바뀌어도 반영 확인을 요구한다.
                    issue.decision_answer_id = answer.question_id
            continue
        question = issue.decision_question
        if not isinstance(question, str) or not question.strip() or not has_hangul(prose(question)):
            raise ReviewValidationError(["user_decision requires a non-empty Korean decision_question."], stage="review_resolution", check="question_text")
        question = question.strip()
        key = decision_identity(issue)
        record = by_key.get(key)
        answer = by_id.get(record["question_id"]) if record else None
        answer = answer or next((by_id[ref.split(":", 1)[1]] for ref in issue.basis_refs if ref.startswith("user_answer:") and ref.split(":", 1)[1] in by_id), None)
        if key in reconfirm_keys:
            record, answer = None, None
        if answer:
            # 답변은 해결 증명이 아니다. 컴파일러가 반영한 뒤 검토에서 다시 판정한다.
            issue.resolution_kind = "auto_fix"
            issue.decision_question = None
            issue.decision_answer_id = answer.question_id
            issue.defect_kind = "spec_omission"
            issue.missing_information = ""
            issue.resolution_reason = "이미 확인한 사용자 답변을 명세에 반영해야 합니다."
            issue.basis_refs = list(dict.fromkeys([*issue.basis_refs, "user_answer:" + answer.question_id]))
            issue.required_change = f"이미 확인한 사용자 결정 [{answer.question_id}]: {answer.answer}\n이 결정을 명세에 반영하고 관련 수용 기준과 테스트를 보완하세요."
            continue
        if record is None:
            record = {"question_id": "REVIEW-" + sha256((key + (text_hash(state.get("revision_feedback", "")) if key in reconfirm_keys else "")).encode()).hexdigest()[:16].upper(),
                      "decision_key": key, "feedback_hash": text_hash(state.get("revision_feedback", "")),
                      "question": question, "issue_ids": [], "problems": [], "required_changes": [], "evidence": [],
                      "review_round": review_round, "requirement_ids": [], "missing_information": [], "resolution_reasons": []}
            from backend.services.question_forms import question_form
            try:
                record["form"] = question_form(record["question_id"], question, issue.decision_form)
            except ValueError as error:
                raise ReviewValidationError(["Invalid decision question form."], stage="review_resolution", check="question_form") from error
            records.append(record)
            by_key[key] = record
        if record["review_round"] != review_round:
            record.update(issue_ids=[], problems=[], required_changes=[], evidence=[], requirement_ids=[], missing_information=[], resolution_reasons=[], review_round=review_round)
        for name, value in (("issue_ids", issue.issue_id), ("problems", issue.problem), ("required_changes", issue.required_change)):
            if value not in record[name]:
                record[name].append(value)
        for name, value in (("requirement_ids", issue.requirement_id), ("missing_information", issue.missing_information), ("resolution_reasons", issue.resolution_reason)):
            if value and value not in record[name]:
                record[name].append(value)
        for evidence in issue.evidence:
            if evidence.to_dict() not in record["evidence"]:
                record["evidence"].append(evidence.to_dict())
        if record["question_id"] not in pending_ids:
            pending_ids.add(record["question_id"])
            pending.append(f'[{record["question_id"]}] {record["question"]}')
    return records, pending
