"""정산 근거는 현재 정책이 명시된 기록만 자동 계산 대상으로 인정한다."""

from backend.access.costs import TOKEN_FIELDS, evidence_status
from backend.model_policy import COST_POLICY, MODEL


def test_calculated_evidence_requires_current_policy():
    row = {key: 0 for key in TOKEN_FIELDS}
    row.update(model=MODEL, settlement_source="calculated")
    assert evidence_status(row) == "unknown"
    row["cost_policy"] = COST_POLICY
    assert evidence_status(row) == "complete"
