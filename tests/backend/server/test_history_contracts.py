"""공개 상세 조회의 과거 기록 경계와 근거 우선순위."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.server.execution_history import ExecutionHistory


ISSUE = {"issue_id": "I1", "requirement_id": "R1", "decision_key": "policy",
         "checklist_id": "C1", "severity": "major", "problem": "규칙 누락"}


def read_detail(nodes):
    history = ExecutionHistory(SimpleNamespace())
    history._load = lambda **kwargs: {"nodes": nodes}
    history._read_document = lambda document: None
    return history.detail("stop")


def stop(**values):
    return {"id": "stop", "stage": "workflow", "status": "blocked", **values}


def test_missing_execution_ids_never_link_unrelated_evidence():
    result = read_detail([{"id": "old", "result": {"structured_issues": [ISSUE]}}, stop()])
    assert result["result"]["stop_diagnostic"]["issues"] == []


def test_explicit_empty_captured_issues_override_previous_structured_issues():
    result = read_detail([
        {"id": "old", "execution_id": "run", "result": {"structured_issues": [ISSUE]}},
        stop(execution_id="run", detail={"issues": []}),
    ])
    assert result["result"]["stop_diagnostic"]["issues"] == []


@pytest.mark.parametrize("field", ["result", "detail"])
def test_invalid_optional_record_is_reported_without_crashing(field):
    result = read_detail([stop(**{field: ["invalid"]})])
    assert result["recording_incomplete"] is True


def test_empty_saved_diagnostic_is_not_treated_as_valid():
    result = read_detail([stop(result={"stop_diagnostic": {}, "structured_issues": [ISSUE]})])
    assert result["result"]["stop_diagnostic"]["issues"][0]["problem"] == "규칙 누락"


def test_detail_does_not_mutate_saved_history():
    nodes = [stop(result={"structured_issues": [ISSUE]})]
    before = deepcopy(nodes)
    result = read_detail(nodes)
    result["result"]["stop_diagnostic"]["issues"][0]["problem"] = "변경"
    assert nodes == before


def test_invalid_latest_issues_do_not_resurrect_previous_review():
    result = read_detail([stop(result={
        "structured_issues": "damaged",
        "resolution_history": [{"issues": [ISSUE]}],
    })])
    diagnostic = result["result"]["stop_diagnostic"]
    assert diagnostic["issues"] == []
    assert diagnostic["recording_incomplete"] is True


def test_only_latest_prior_evidence_from_same_explicit_execution_is_used():
    latest = {**ISSUE, "problem": "같은 실행의 최신 결함"}
    nodes = [
        {"id": "first", "execution_id": "a", "result": {"structured_issues": [ISSUE]}},
        {"id": "second", "execution_id": "a", "result": {"structured_issues": [latest]}},
        {"id": "other", "execution_id": "b", "result": {"structured_issues": []}},
        stop(execution_id="a"),
        {"id": "future", "execution_id": "a", "result": {"structured_issues": []}},
    ]
    assert read_detail(nodes)["result"]["stop_diagnostic"]["issues"][0]["problem"] == latest["problem"]


def test_valid_saved_diagnostic_is_authoritative_over_previous_evidence():
    from backend.services.stop_diagnostics import stop_diagnostic

    stored = stop_diagnostic({"structured_issues": []})
    result = read_detail([
        {"id": "old", "execution_id": "a", "result": {"structured_issues": [ISSUE]}},
        stop(execution_id="a", result={"stop_diagnostic": stored}),
    ])
    assert result["result"]["stop_diagnostic"] == stored
