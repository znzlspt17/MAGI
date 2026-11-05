"""여러 테스트에서 공유하는 검증용 도우미."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from backend.models import RequirementItem, RequirementLockSheet, RubricResponse, ReviewResponse
from backend.services import rubric
from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS, _assemble_locked_sections


class Documents:
    def __init__(self):
        self.data = {}

    def exists(self, path):
        return path in self.data

    def read_json(self, path):
        return deepcopy(self.data[path])

    def write_json(self, path, value, **kwargs):
        self.data[path] = deepcopy(value)


@pytest.fixture
def case(monkeypatch):
    sheet = RequirementLockSheet("lock", "feature", "메모", [],
        mandatory_requirements=[RequirementItem("REQ-001", "메모를 로컬에 저장합니다.", original_text="메모 저장")])
    state = {"user_request": "메모 저장", "requirement_lock_sheet": sheet.to_dict()}
    response = RubricResponse(items=[dict(rubric_id="RUB-001", requirement_id="REQ-001", category="requirement", importance="core",
        basis=[dict(reference="REQ-001", quote="메모를 로컬에 저장합니다.")],
        condition="메모의 로컬 저장이 명시되어 있는지 검증합니다.", sections=["architecture", "test_plan"])])
    complete = Mock(return_value=response)
    monkeypatch.setattr(rubric, "complete_with_usage", complete)
    docs = Documents()
    record = rubric.ensure_rubric(docs, None, "model", sheet, state)
    state["rubric"] = record
    spec = "\n\n".join(heading + "\n\n메모를 로컬에 저장합니다. Windows에서 로컬 저장을 검증합니다."
                         for heading in REQUIRED_FINAL_SPEC_HEADINGS)
    spec = _assemble_locked_sections(spec, sheet)
    verdict = dict(rubric_id="RUB-001", verdict="PASS", section="architecture", evidence_kind="quote",
                   quote="메모를 로컬에 저장합니다.", reason="명세에 저장 동작이 반영되어 있습니다.", issue_checklist_id=None)
    return SimpleNamespace(sheet=sheet, state=state, response=response, complete=complete, docs=docs,
                           record=record, spec=spec, verdict=verdict)


def review(case, **changes):
    return ReviewResponse(score=10, score_reason="모든 기준을 충족합니다.", critical_failures=[], revision_directives=[], issues=[], rubric_verdicts=[{**case.verdict, **changes}])


def failed_review(case, verdict="FAIL"):
    issue = dict(rubric_ids=["RUB-001"], defect_kind="verification_gap", resolution_reason="검증 방법이 누락됐습니다.",
        missing_information="", decision_key="RUB-001", section="test_plan", severity="major", checklist_id="RUB-001",
        problem="저장 검증 절차가 없습니다.", required_change="확정된 저장 동작을 확인하는 테스트를 보완하세요.",
        requirement_id="REQ-001", evidence=[dict(source="test_plan", quote="")])
    return ReviewResponse(score=4, score_reason="필수 동작을 보완해야 합니다.", critical_failures=["RUB-001"], revision_directives=["저장 테스트를 보완하세요."], issues=[issue], rubric_verdicts=[{**case.verdict, "verdict": verdict, "section": "test_plan",
        "evidence_kind": "absence", "quote": "", "issue_checklist_id": "RUB-001"}])
