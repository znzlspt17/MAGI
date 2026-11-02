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


POLICY_VERSION = 2
PATH = "review/rubric.json"
EVALUATION_PATH = "review/rubric_evaluation.json"
GROUPS = ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints", "non_scope")
SECTIONS = frozenset(SpecResponse.model_fields) - {"decisions", "spec_links"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def invalid(check, *, stage="rubric_generate"):
    # 제공자 원문은 예외나 공개 진단에 복사하지 않는다.
    return ReviewValidationError(["Return a complete grounded rubric or evaluation matching the supplied contract."],
                                 stage=stage, check=check)


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
    covered = set()
    for item in response.items:
        if (item.requirement_id not in known or not item.condition.strip()
                or len(item.sections) != len(set(item.sections)) or not set(item.sections) <= SECTIONS):
            raise invalid("rubric_basis")
        # 각 조건은 자신의 제품 요구사항을 직접 인용해야 한다.
        if not any(entry.reference == item.requirement_id for entry in item.basis):
            raise invalid("rubric_basis")
        for entry in item.basis:
            if (entry.reference not in {item.requirement_id, item.requirement_id + ".original_text"}
                    or entry.reference not in basis or not entry.quote.strip()
                    or entry.quote not in basis[entry.reference]):
                raise invalid("rubric_basis")
        try:
            validate_product_boundary(sheet, [item.model_dump_json()])
        except ValueError:
            raise invalid("rubric_boundary") from None
        covered.add(item.requirement_id)
    if not {item.id for item in [*sheet.mandatory_requirements, *sheet.constraints]} <= covered:
        raise invalid("rubric_coverage")


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

    def fail(check):
        raise invalid(check, stage="checklist_critic")

    items = {item["rubric_id"]: item for item in rubric["items"]}
    verdicts = response.rubric_verdicts
    ids = [item.rubric_id for item in verdicts]
    if len(ids) != len(set(ids)) or set(ids) != set(items):
        fail("rubric_evaluation_coverage")
    sections = _rendered_sections(spec)
    issues = response.issues
    by_id = {item.rubric_id: item for item in verdicts}
    for issue in issues:
        if len(issue.rubric_ids) != len(set(issue.rubric_ids)) or not set(issue.rubric_ids) <= set(items):
            fail("rubric_issue")
        for rubric_id in issue.rubric_ids:
            verdict = by_id[rubric_id]
            if (verdict.verdict == "PASS" or verdict.issue_checklist_id != issue.checklist_id
                    or items[rubric_id]["requirement_id"] != issue.requirement_id):
                fail("rubric_issue")
    for verdict in verdicts:
        item = items[verdict.rubric_id]
        if verdict.section not in item["sections"] or verdict.section not in sections or not verdict.reason.strip():
            fail("rubric_evidence")
        if verdict.evidence_kind == "quote":
            if not verdict.quote.strip() or verdict.quote not in sections[verdict.section]:
                fail("rubric_evidence")
        elif verdict.quote or verdict.verdict == "PASS":
            fail("rubric_evidence")
        matches = [issue for issue in issues if verdict.rubric_id in issue.rubric_ids]
        if verdict.verdict == "PASS":
            if verdict.issue_checklist_id is not None or matches:
                fail("rubric_issue")
        elif (len(matches) != 1 or matches[0].severity not in {"blocking", "major"}
                or not any(e.source == verdict.section and e.quote == verdict.quote for e in matches[0].evidence)):
            fail("rubric_issue")
    return {"rubric_hash": rubric["rubric_hash"], "draft_hash": hashlib.sha256(spec.encode()).hexdigest(),
            "verdicts": [item.model_dump() for item in verdicts]}


def save_evaluation(writer, evaluation):
    key = digest(evaluation)
    writer.write_json(f"review/rubric_evaluations/{key}.json", evaluation)
    writer.write_json(EVALUATION_PATH, evaluation)


def require_approval_evaluation(state, sheet, spec):
    rubric = state.get("rubric", {})
    evaluation = state.get("rubric_evaluation", {})
    if (not current_record(rubric, sheet, state) or not isinstance(evaluation, dict)
            or evaluation.get("rubric_hash") != rubric["rubric_hash"]
            or evaluation.get("draft_hash") != hashlib.sha256(spec.encode()).hexdigest()):
        raise invalid("rubric_stale", stage="compose_candidate")
    verdicts = evaluation.get("verdicts", [])
    expected = {item["rubric_id"] for item in rubric["items"]}
    try:
        response = ReviewResponse(issues=[], rubric_verdicts=verdicts)
        if (len(response.rubric_verdicts) != len(expected)
                or any(item.verdict != "PASS" for item in response.rubric_verdicts)):
            raise invalid("rubric_stale", stage="compose_candidate")
        validate_evaluation(response, rubric, spec)
    except (ValidationError, ReviewValidationError):
        raise invalid("rubric_stale", stage="compose_candidate") from None


def summary(rubric, evaluation=None):
    counts = {name: 0 for name in ("PASS", "FAIL", "UNDETERMINED")}
    for item in (evaluation or {}).get("verdicts", []):
        counts[item["verdict"]] += 1
    return {"status": "evaluated" if evaluation is not None else "ready", "policy_version": POLICY_VERSION,
            "item_count": len(rubric["items"]), **counts}
