"""확정 제품 근거에서 생성한 검사 기준과 초안별 평가의 수명을 관리한다."""

from __future__ import annotations

import hashlib
import json
from pydantic import ValidationError

from backend.errors import ReviewValidationError
from backend.infrastructure.prompt_messages import messages
from backend.infrastructure.prompts import load_prompt
from backend.infrastructure.provider_call import complete_with_usage
from backend.models import RubricResponse, ReviewResponse, SpecResponse
from backend.services.review_resolution import confirmed_basis
from backend.services.workflow_constraints import user_sources, validate_product_boundary


POLICY_VERSION = 4
PATH = "review/rubric.json"
EVALUATION_PATH = "review/rubric_evaluation.json"
GROUPS = ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints", "non_scope")
SECTIONS = frozenset(SpecResponse.model_fields) - {"decisions", "spec_links"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def invalid(check, *, stage="rubric_generate", reason=None, context=None):
    # 제공자 원문은 예외나 공개 진단에 복사하지 않는다.
    return ReviewValidationError(["Return a complete grounded rubric or evaluation matching the supplied contract."],
                                 stage=stage, check=check, reason=reason, context=context)


def inputs(sheet, state):
    requirements = {item.id: item for group in GROUPS for item in getattr(sheet, group)}
    basis = {key: item.text for key, item in requirements.items()}
    actual = user_sources(state)
    for key, item in requirements.items():
        if item.original_text.strip() and any(item.original_text in text
                for text in actual.get(item.source, []) if isinstance(text, str)):
            basis[key + ".original_text"] = item.original_text
    product = {group: [{"id": item.id, "text": item.text} for item in getattr(sheet, group)] for group in GROUPS}
    # 초안·검토 결과·lock_id는 기준을 바꾸지 않는다. 확정 입력 변경은 반드시 무효화한다.
    input_hash = digest([POLICY_VERSION, product, basis, sheet.decisions, sheet.acceptance_criteria_seed,
                         confirmed_basis(state, sheet.to_dict()), state.get("revision_history", [])])
    return {"requirements": product, "confirmed_basis": basis, "sections": sorted(SECTIONS)}, input_hash


def validate_items(response, sheet, canonical):
    if not isinstance(response, RubricResponse):
        raise invalid("rubric_schema")
    ids = [item.rubric_id for item in response.items]
    if len(ids) != len(set(ids)):
        raise invalid("rubric_identity")
    basis = canonical["confirmed_basis"]
    known = {item.id for group in GROUPS for item in getattr(sheet, group)}
    optional = {item.id for group in (sheet.optional_requirements, sheet.recommended_requirements) for item in group}
    covered = set()
    for item in response.items:
        if item.requirement_id not in known:
            raise invalid("rubric_basis", reason="requirement_unknown")
        context = {"requirement_id": item.requirement_id}
        if not item.condition.strip():
            raise invalid("rubric_basis", reason="condition_missing", context=context)
        if len(item.sections) != len(set(item.sections)) or not set(item.sections) <= SECTIONS:
            raise invalid("rubric_basis", reason="section_invalid", context=context)
        if item.requirement_id in optional and item.importance != "secondary":
            raise invalid("rubric_basis", reason="importance_invalid", context=context)
        # 각 조건은 자신의 제품 요구사항을 직접 인용해야 한다.
        if not any(entry.reference == item.requirement_id for entry in item.basis):
            raise invalid("rubric_basis", reason="basis_reference_invalid", context=context)
        for entry in item.basis:
            if entry.reference not in {item.requirement_id, item.requirement_id + ".original_text"} or entry.reference not in basis:
                raise invalid("rubric_basis", reason="basis_reference_invalid", context=context)
            if not entry.quote.strip() or entry.quote not in basis[entry.reference]:
                raise invalid("rubric_basis", reason="basis_quote_not_found", context=context)
        try:
            validate_product_boundary(sheet, [item.model_dump_json()])
        except ValueError:
            raise invalid("rubric_boundary") from None
        covered.add(item.requirement_id)
    if not {item.id for item in [*sheet.mandatory_requirements, *sheet.constraints]} <= covered:
        raise invalid("rubric_coverage", reason="rubric_coverage_missing",
                      context={"expected_count": len({item.id for item in [*sheet.mandatory_requirements, *sheet.constraints]}),
                               "actual_count": len(covered & {item.id for item in [*sheet.mandatory_requirements, *sheet.constraints]})})


def current_record(record, sheet, state):
    canonical, input_hash = inputs(sheet, state)
    if not isinstance(record, dict) or record.get("input_hash") != input_hash or record.get("policy_version") != POLICY_VERSION:
        return False
    try:
        response = RubricResponse.model_validate({"items": record.get("items")})
        validate_items(response, sheet, canonical)
    except (ValidationError, ReviewValidationError):
        return False
    return record.get("rubric_hash") == digest([POLICY_VERSION, input_hash, response.model_dump()])


def ensure_rubric(writer, provider, model, sheet, state):
    sheet.require_validated()
    canonical, input_hash = inputs(sheet, state)
    record = state.get("rubric", {})
    if current_record(record, sheet, state):
        return record
    # 검증 재시도나 작업 재개에서도 이미 완료한 생성 호출을 반복하지 않는다.
    if writer.exists(PATH):
        record = writer.read_json(PATH)
        if current_record(record, sheet, state):
            return record
    response = complete_with_usage(writer, provider,
        messages(load_prompt("rubric_generate"), "", json.dumps(canonical, ensure_ascii=False)),
        model=model, stage="rubric_generate", temperature=0)
    validate_items(response, sheet, canonical)
    record = {"policy_version": POLICY_VERSION, "input_hash": input_hash,
              "rubric_hash": digest([POLICY_VERSION, input_hash, response.model_dump()]), **response.model_dump()}
    writer.write_json(f"review/rubrics/{record['rubric_hash']}.json", record)
    writer.write_json(PATH, record)
    return record


def validate_evaluation(response: ReviewResponse, rubric, spec):
    """모델 판정을 실제 섹션·인용 및 필수 결함과 연결한다. 의미적 증명은 아니다."""
    from backend.services.spec_compiler import _rendered_sections

    def fail(check, reason=None, context=None):
        raise invalid(check, stage="checklist_critic", reason=reason, context=context)

    items = {item["rubric_id"]: item for item in rubric["items"]}
    verdicts = response.rubric_verdicts
    ids = [item.rubric_id for item in verdicts]
    if len(ids) != len(set(ids)) or set(ids) != set(items):
        fail("rubric_evaluation_coverage", "evaluation_coverage_mismatch", {"expected_count": len(items), "actual_count": len(ids)})
    sections = _rendered_sections(spec)
    issues = response.issues
    by_id = {item.rubric_id: item for item in verdicts}
    for issue in issues:
        if len(issue.rubric_ids) != len(set(issue.rubric_ids)) or not set(issue.rubric_ids) <= set(items):
            fail("rubric_issue", "issue_link_invalid")
        for rubric_id in issue.rubric_ids:
            verdict = by_id[rubric_id]
            if (verdict.verdict == "PASS" or verdict.issue_checklist_id != issue.checklist_id
                    or items[rubric_id]["requirement_id"] != issue.requirement_id):
                fail("rubric_issue", "issue_link_invalid", {"rubric_id": rubric_id, "requirement_id": items[rubric_id]["requirement_id"]})
    for verdict in verdicts:
        item = items[verdict.rubric_id]
        context = {"rubric_id": verdict.rubric_id, "requirement_id": item["requirement_id"], "allowed_sections": item["sections"]}
        if verdict.section not in item["sections"] or verdict.section not in sections:
            fail("rubric_evidence", "section_invalid", context)
        if not verdict.reason.strip():
            fail("rubric_evidence", "reason_missing", context)
        if verdict.evidence_kind == "quote":
            if not verdict.quote.strip() or verdict.quote not in sections[verdict.section]:
                fail("rubric_evidence", "quote_not_found", context)
        elif verdict.quote or verdict.verdict == "PASS":
            fail("rubric_evidence")
        matches = [issue for issue in issues if verdict.rubric_id in issue.rubric_ids]
        if verdict.verdict == "PASS":
            if verdict.issue_checklist_id is not None or matches:
                fail("rubric_issue", "issue_link_invalid", context)
        elif (len(matches) != 1 or matches[0].severity not in ({"blocking", "major", "minor"} if item["importance"] == "secondary" else {"blocking", "major"})
                or not any(e.source == verdict.section and e.quote == verdict.quote for e in matches[0].evidence)):
            fail("rubric_issue", "issue_link_invalid", context)
    failed = [item for item in verdicts if item.verdict != "PASS"]
    critical = {item.rubric_id for item in failed if items[item.rubric_id]["importance"] != "secondary"}
    critical.update(issue.checklist_id for issue in issues if issue.severity in {"blocking", "major"} and not issue.rubric_ids)
    cap = 4 if any(items[item.rubric_id]["importance"] == "core" for item in failed) else 7 if critical or any(issue.severity in {"blocking", "major"} for issue in issues) else 9 if failed or issues else 10
    if (not response.score_reason.strip()
            or ((failed or issues) and not response.revision_directives)
            or any(not value.strip() for value in response.revision_directives)):
        fail("rubric_score", "score_invalid")
    return {"rubric_hash": rubric["rubric_hash"], "draft_hash": hashlib.sha256(spec.encode()).hexdigest(),
            "verdicts": [item.model_dump() for item in verdicts],
            **response.model_dump(exclude={"rubric_verdicts", "score", "critical_failures"}),
            "proposed_score": response.score, "score": min(response.score, cap),
            "critical_failures": sorted(critical)}


def save_evaluation(writer, evaluation):
    key = digest(evaluation)
    writer.write_json(f"review/rubric_evaluations/{key}.json", evaluation)
    writer.write_json(EVALUATION_PATH, evaluation)


def deterministic_score_cap(issues):
    """2026-11-05: 생성 시점과 승인 재검증에 동일한 결정적 상한을 적용한다."""
    if any(item.severity in {"blocking", "major"} for item in issues):
        return 7
    return 9 if issues else 10


def apply_deterministic_evaluation(evaluation, issues):
    critical = set(evaluation["critical_failures"])
    critical.update(item.checklist_id for item in issues if item.severity in {"blocking", "major"})
    return {**evaluation, "score": min(evaluation["score"], deterministic_score_cap(issues)),
            "critical_failures": sorted(critical)}


def require_approval_evaluation(state, sheet, spec):
    rubric = state.get("rubric", {})
    evaluation = state.get("rubric_evaluation", {})
    if not current_record(rubric, sheet, state):
        raise invalid("rubric_stale", stage="compose_candidate", reason="rubric_input_changed")
    if not isinstance(evaluation, dict) or not evaluation:
        raise invalid("rubric_stale", stage="compose_candidate", reason="evaluation_missing")
    if evaluation.get("rubric_hash") != rubric["rubric_hash"] or evaluation.get("draft_hash") != hashlib.sha256(spec.encode()).hexdigest():
        raise invalid("rubric_stale", stage="compose_candidate", reason="evaluation_draft_mismatch")
    try:
        response = ReviewResponse.model_validate({**{key: evaluation[key] for key in
            ("score_reason", "critical_failures", "revision_directives", "issues")},
            "score": evaluation.get("proposed_score", evaluation["score"]),
            "rubric_verdicts": evaluation["verdicts"]})
        checked = validate_evaluation(response, rubric, spec)
        from backend.services.checklist_critic import run_deterministic_checks
        deterministic = run_deterministic_checks(spec, sheet)
        checked = apply_deterministic_evaluation(checked, deterministic)
        if checked["critical_failures"] != evaluation["critical_failures"] or checked["score"] != evaluation["score"]:
            raise ValueError("stored derived values invalid")
    except (KeyError, ValidationError, ReviewValidationError, ValueError):
        raise invalid("rubric_stale", stage="compose_candidate", reason="stored_evaluation_invalid") from None


def summary(rubric, evaluation=None):
    counts = {name: 0 for name in ("PASS", "FAIL", "UNDETERMINED")}
    for item in (evaluation or {}).get("verdicts", []):
        counts[item["verdict"]] += 1
    return {"status": "evaluated" if evaluation is not None else "ready", "policy_version": POLICY_VERSION,
            "item_count": len(rubric["items"]), **counts}
