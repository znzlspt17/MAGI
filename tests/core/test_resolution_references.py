"""확정 근거 ID와 모델용 출처 참조가 같은 계약을 사용하는지 확인한다."""

import json

import pytest

from backend.errors import ReviewValidationError
from backend.infrastructure.prompt_context import prepare_context
from backend.infrastructure.prompt_messages import messages
from backend.models import ReviewResolutionResponse
from fakes import resolution_value


def context():
    payload = messages("검토", "메모 앱", json.dumps({
        "confirmed_basis": {"FR-001": "Save notes.", "user_request": "메모 앱"},
        "issues": [], "previous_resolutions": [], "review_questions": [], "diagnose_keys": [],
    }))
    prepared, refs = prepare_context(None, payload, "review_resolution")
    canonical = json.loads(next(item["content"].split("\n", 1)[1] for item in prepared
                                if item["content"].startswith("Canonical context:\n")))
    return canonical, refs


def packet(ref):
    value = resolution_value([{"issue_id": "I1", "requirement_id": ref,
                               "decision_key": "storage", "required_change": "저장을 보완하세요."}])
    return ReviewResolutionResponse.model_validate(value)


@pytest.mark.parametrize("ref", ["FR-001", "S1"])
def test_supplied_product_id_and_source_restore(ref):
    canonical, refs = context()
    assert canonical["allowed_resolution_refs"]["basis_refs"] == ["FR-001", "S1"]
    restored = refs.restore(packet(ref))
    assert restored.resolutions[0].basis_refs == (["user_request"] if ref == "S1" else [ref])


@pytest.mark.parametrize("ref", ["FR-999", "S999", "WF-001", "I1", "user_request"])
def test_unknown_references_still_fail_with_actionable_repair_context(ref):
    _, refs = context()
    with pytest.raises(ReviewValidationError) as caught:
        refs.restore(packet(ref))
    assert caught.value.failed_checks == ["source_reference"]
    detail = caught.value.validation_details[0]
    assert "allowed_resolution_refs.basis_refs" in detail
    assert '["FR-001", "S1"]' in detail


def test_conflicting_source_does_not_accept_product_id():
    _, refs = context()
    result = packet("FR-001")
    result.resolutions[0].conflicting_source = "FR-001"
    with pytest.raises(ReviewValidationError) as caught:
        refs.restore(result)
    assert "allowed_resolution_refs.conflicting_source: []" in caught.value.validation_details[0]
