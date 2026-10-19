"""명세 추적 검증 실패의 보정 예산과 안전한 진단을 검증한다."""

import json

import pytest

from backend.config import MagiConfig
from backend.errors import SpecCompilationError
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.knowledge.trace import SpecLink, validate_links, TraceValidationError
from backend.models import CompletionResult, RequirementLockSheet, SpecResponse
from backend.pipeline.builder import _stage
from backend.server.diagnostics import diagnose_exception
from backend.server.job_manager import JobManager
from backend.services.skill_registry import SkillRegistry
from backend.services.spec_compiler import SpecCompiler, _anchor_links


@pytest.fixture(autouse=True)
def legacy_response_contract(monkeypatch):
    # 이 파일은 기존 문자열 응답의 검증·호환 경로를 유지한다. 새 wire 계약은 별도 SDK 테스트에서 검증한다.
    from backend.models import STAGE_SCHEMAS
    monkeypatch.setitem(STAGE_SCHEMAS, "spec_compile", SpecResponse)


def sheet():
    return RequirementLockSheet.from_dict({"workflow_constraints": [], "mandatory_requirements": [
        {"id": "REQ-001", "text": "Store notes locally.", "source": "user_request"}]})


class Provider:
    def __init__(self, fail_count):
        self.fail_count, self.calls = fail_count, []

    def complete_result(self, messages, **kwargs):
        self.calls.append(messages)
        value = SpecResponse(**{field: "Store notes locally." for field in SpecResponse.model_fields
                                if field not in {"decisions", "spec_links"}})
        value.spec_links = [SpecLink(item_id="S1", section="architecture",
            quote="untrusted-response-marker" if len(self.calls) <= self.fail_count else "Store notes locally.",
            requirement_ids=["REQ-001"], decision_ids=[])]
        return CompletionResult(text="", parsed=value)


def compiler(provider):
    return SpecCompiler(config=MagiConfig.default(), provider=provider, skills=SkillRegistry(), evidence=None)


def test_direct_compile_repairs_exact_quote_without_weakening_validation():
    provider = Provider(1)
    result = compiler(provider).compile(sheet(), {}, user_request="메모")
    assert "Store notes locally." in result and len(provider.calls) == 2
    retry = json.loads(provider.calls[-1][-1]["content"].split("\n", 1)[1])
    assert "spec_links[0].quote" in retry["validation_failures"][0]
    assert "untrusted-response-marker" not in json.dumps(retry)
    assert not any(item["role"] == "assistant" for item in provider.calls[-1])


def test_valid_quote_after_internal_heading_survives_rendered_validation():
    class NestedProvider(Provider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            result.parsed.architecture = "Overview.\n\n## Internal components\n\nStore notes locally."
            return result
    provider = NestedProvider(0)
    assert "## Internal components" in compiler(provider).compile(sheet(), {})
    assert len(provider.calls) == 1


def test_whitespace_anchor_is_real_unique_source_and_semantic_changes_fail():
    original = {"item_id": "S1", "section": "architecture", "quote": "Store notes locally.",
                "requirement_ids": ["REQ-001"], "decision_ids": []}
    sections = {"architecture": "Store notes\n  locally."}
    anchored = _anchor_links([original], sections, "response")
    assert anchored[0]["quote"] == sections["architecture"]
    assert original["quote"] == "Store notes locally."
    validate_links(anchored, [], sheet().to_dict(), sections)
    for text in ("Store notes remotely.", "Store notes\nlocally. And Store notes\nlocally."):
        with pytest.raises(SpecCompilationError) as failure:
            _anchor_links([original], {"architecture": text}, "assembled")
        assert failure.value.validation_phase == "assembled"
        assert failure.value.validation_location["index"] == 0


def test_pipeline_shares_four_call_budget_and_persists_safe_error(tmp_path):
    provider = Provider(99)
    service = compiler(provider)
    writer = ArtifactWriter(tmp_path)
    # 외부 통신·사용량 기록 경로 대신 모의 제공자의 구조화 결과만 사용한다.
    from unittest.mock import patch
    from backend.infrastructure.provider_call import complete_direct
    def complete(_writer, _provider, messages, **kwargs):
        return complete_direct(_provider, messages, model=kwargs["model"], stage=kwargs["stage"])
    with patch("backend.services.spec_compiler.complete_with_usage", complete):
        with pytest.raises(SpecCompilationError) as failure:
            _stage("spec_compile", lambda state: service.compile(sheet(), {}, writer=writer), None)({})
    assert len(provider.calls) == 4
    saved = writer.read_json("analysis/spec_compile_validation.json")
    assert saved["attempt"] == 4 and "untrusted-response-marker" not in json.dumps(saved)
    diagnostic = diagnose_exception(failure.value)
    assert diagnostic["error_code"] == "SPEC_COMPILATION_INVALID"
    assert diagnostic["error_stage"] == "spec_compile"
    job = {}
    JobManager._set_error_metadata(job, diagnostic)
    assert JobManager._valid_error_metadata(job)
    assert job == {"error_code": "SPEC_COMPILATION_INVALID", "error_stage": "spec_compile"}


def test_compile_failure_can_be_revised_only_with_recoverable_saved_state(tmp_path, monkeypatch):
    manager = JobManager(tmp_path)
    job = {"id": "a" * 32, "status": "error", "error_code": "SPEC_COMPILATION_INVALID"}
    try:
        monkeypatch.setattr(manager, "_has_recoverable_normalization_state_locked", lambda ident: True)
        assert manager._normalization_retry_allowed_locked(job, "revise")
        assert not manager._normalization_retry_allowed_locked(job, "approve")
        monkeypatch.setattr(manager, "_has_recoverable_normalization_state_locked", lambda ident: False)
        assert not manager._normalization_retry_allowed_locked(job, "revise")
    finally:
        manager.close()


@pytest.mark.parametrize("change,field", [({"section": "## 13. Architecture"}, "section"),
    ({"section": "decisions"}, "section"), ({"requirement_ids": ["REQ-MISSING"]}, "requirement_ids"),
    ({"decision_ids": ["DEC-MISSING"]}, "decision_ids")])
def test_trace_diagnostics_identify_invalid_field_without_accepting_it(change, field):
    link = {"item_id": "S1", "section": "architecture", "quote": "Store notes locally.",
            "requirement_ids": ["REQ-001"], "decision_ids": [], **change}
    with pytest.raises(TraceValidationError) as failure:
        validate_links([link], [], sheet().to_dict(), {"architecture": "Store notes locally.", "decisions": []})
    assert f"spec_links[0].{field}" in failure.value.validation_details[0]
