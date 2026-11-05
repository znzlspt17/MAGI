import hashlib

from backend.application.document_queries import DocumentQueries
from backend.infrastructure.output_language import language_issues
from backend.models import RubricResponse, RequirementItem, RequirementLockSheet
from backend.services.implementation_package import create_package
from backend.services.checklist import _PLACEHOLDER_ACCEPTANCE, _GENERIC_COMPLETION_ACCEPTANCE
from backend.services.spec_compiler import _assemble_locked_sections, _rendered_sections, SpecCompiler, REQUIRED_FINAL_SPEC_HEADINGS


def test_document_returns_korean_source_without_provider():
    query = object.__new__(DocumentQueries)
    source = "# 명세\n\nAPI 요청을 저장한다."
    query.step = lambda ident, step: {"document": {"content": source, "filename": "SPEC.ko.md", "source_hash": hashlib.sha256(source.encode()).hexdigest()}}
    result = query.document("job", "step")
    assert result["language"] == "ko"
    assert result["content"] == source
    assert result["source_hash"] == hashlib.sha256(source.encode()).hexdigest()


def test_rubric_requires_korean_condition():
    item = {"rubric_id": "RUB-1", "requirement_id": "REQ-1", "importance": "core", "category": "requirement", "basis": [{"reference": "REQ-1", "quote": "저장"}], "condition": "요청을 저장한다", "sections": ["mission"]}
    assert not language_issues(RubricResponse(items=[item]))
    item["condition"] = "Store the request"
    assert language_issues(RubricResponse(items=[item])) == ["items[0].condition: ko"]


def test_package_has_korean_spec_as_authoritative_content():
    source = "# 최종 에이전트 명세\n\n한국어 명세입니다."
    _, files = create_package("a" * 64, {"content": source})
    assert files["SPEC.ko.md"].decode() == source
    assert "SPEC.en.md" not in files
    assert "SPEC.ko.md" in files["README.ko.md"].decode()


def test_korean_generic_acceptance_is_not_a_product_verification():
    assert _PLACEHOLDER_ACCEPTANCE.match("- 최종 명세에 포함...")
    assert _GENERIC_COMPLETION_ACCEPTANCE.match("- 최종 명세에 범위, 금지 행동, 수용 기준과 테스트 계획이 포함되어 있다.")
    assert not _GENERIC_COMPLETION_ACCEPTANCE.match("- 사용자는 저장한 항목을 다시 조회할 수 있다.")


def test_korean_headings_assemble_and_extract_locked_sections():
    sheet = RequirementLockSheet(lock_id="lock", request_type="feature", request_summary="메모",
        workflow_constraints=[], mandatory_requirements=[RequirementItem("REQ-1", "메모를 저장한다.")],
        non_scope=[RequirementItem("NS-1", "동기화는 제외한다.")],
        constraints=[RequirementItem("CON-1", "외부 네트워크 사용을 금지한다.")])
    draft = "## 4. 범위\n\n### 4.1 범위 포함\n\n내용\n\n### 4.2 범위 제외\n\n이전\n\n## 7. 필수 요구사항\n\n이전\n\n## 10. 금지 행동\n\n내용\n\n## 11. 입력 계약\n\n입력"
    result = _assemble_locked_sections(draft, sheet)
    assert "- [REQ-1] 메모를 저장한다." in result
    assert "- [NS-1] 동기화는 제외한다." in result
    assert "### 확정된 제약\n\n다음 확정 제약을 위반해서는 안 됩니다.\n\n- [CON-1] 외부 네트워크 사용을 금지한다." in result
    assert "동기화는 제외한다" in _rendered_sections(result)["out_of_scope"]


def test_korean_heading_does_not_make_english_prose_valid():
    english = "\n\n".join(f"{heading}\n\nSave each request safely." for heading in REQUIRED_FINAL_SPEC_HEADINGS)
    korean = "\n\n".join(f"{heading}\n\n요청을 저장합니다." for heading in REQUIRED_FINAL_SPEC_HEADINGS)
    assert not SpecCompiler.korean_document(english)
    assert SpecCompiler.korean_document(korean)
    technical = korean.replace("## 1. 목표\n\n요청을 저장합니다.", "## 1. 목표\n\n`HTTP`")
    assert SpecCompiler.korean_document(technical)
    quoted = korean.replace("## 1. 목표\n\n요청을 저장합니다.", "## 1. 목표\n\n<original_quote>Save as-is</original_quote>")
    assert SpecCompiler.korean_document(quoted)
