"""모델 블록과 앱 소유 잠금 섹션의 경계·재시도 계약을 검증한다."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from backend.errors import SpecCompilationError
from backend.models import RequirementItem, RequirementLockSheet, SpecDraftResponse, assemble_spec_draft
from task_fixture import with_tasks


@pytest.fixture
def sheet():
    return RequirementLockSheet(lock_id="test", request_type="feature", request_summary="메모 저장",
        workflow_constraints=[], mandatory_requirements=[RequirementItem("REQ-001", "Store notes locally.")])


@pytest.fixture
def draft():
    return SpecDraftResponse(**with_tasks({name: [{"item_id": "ITEM-" + name,
        "text": "Store notes locally. Verify local persistence on Windows.",
        "requirement_ids": ["REQ-001"] if name == "architecture" else [], "decision_ids": []}]
        for name in SpecDraftResponse.model_fields if name != "decisions"}))


@pytest.mark.parametrize("locked", [False, True])
def test_application_owned_out_of_scope_does_not_require_model_blocks(draft, sheet, locked):
    if locked:
        sheet.non_scope = [RequirementItem("NS-001", "Cloud synchronization is excluded.")]
    draft.out_of_scope = []
    result = assemble_spec_draft(draft, sheet)
    expected = "- [NS-001] Cloud synchronization is excluded." if locked else "No explicit product exclusions were supplied."
    assert result.out_of_scope == expected
    assert [link.item_id for link in result.spec_links if link.section == "out_of_scope"] == (["LOCKED-NS-001"] if locked else [])


def test_discarded_out_of_scope_cannot_collide_with_generated_block_ids(draft, sheet):
    draft.out_of_scope = [draft.architecture[0].model_copy(update={"text": "DISCARDED_MODEL_TEXT"})]
    result = assemble_spec_draft(draft, sheet)
    assert "DISCARDED_MODEL_TEXT" not in result.markdown()


@pytest.mark.parametrize("mutation,reason", [
    ("empty", "empty_section"), ("duplicate", "duplicate_item_id"), ("reserved", "reserved_item_id"), ("empty_id", "empty_item_id"),
    ("blank", "empty_text"), ("unknown_ref", "unknown_requirement"), ("unknown_decision", "unknown_decision"),
    ("heading", "fixed_heading"),
])
def test_generated_content_keeps_strict_validation(draft, sheet, mutation, reason):
    if mutation == "empty": draft.background = []
    elif mutation == "duplicate": draft.background[0].item_id = draft.mission[0].item_id
    elif mutation == "empty_id": draft.background[0].item_id = "   "
    elif mutation == "reserved": draft.background[0].item_id = "LOCKED-NS-001"
    elif mutation == "blank": draft.background[0].text = "   "
    elif mutation == "unknown_ref": draft.background[0].requirement_ids = ["UNKNOWN-001"]
    elif mutation == "unknown_decision": draft.background[0].decision_ids = ["UNKNOWN-001"]
    else: draft.background[0].text = "## 2. Background\nRepeated heading."
    with pytest.raises(SpecCompilationError) as error:
        assemble_spec_draft(draft, sheet)
    assert error.value.failed_checks == ["spec_blocks"]
    from backend.server.diagnostics import diagnose_exception
    diagnostic = diagnose_exception(error.value)
    assert diagnostic["validation_reason"] == reason
    assert diagnostic["validation_section"] == "background"
    assert diagnostic["validation_index"] == (None if mutation == "empty" else 0)
    assert diagnostic["validation_field"] == {"duplicate": "item_id", "reserved": "item_id", "empty_id": "item_id", "blank": "text", "unknown_ref": "requirement_ids", "unknown_decision": "decision_ids", "heading": "text"}.get(mutation)
    assert "UNKNOWN-001" not in str(diagnostic)


def compiler_and_writer():
    from backend.config import Config
    from backend.services.spec_compiler import SpecCompiler
    from backend.services.skill_registry import SkillRegistry
    writer = Mock(runtime=None, state={})
    writer.exists.return_value = False
    return SpecCompiler(config=Config(), provider=Mock(), skills=SkillRegistry()), writer


def test_compiler_persists_only_canonical_non_scope_blocks(draft, sheet, monkeypatch):
    from backend.services.change_review import BLOCKS
    sheet.non_scope = [RequirementItem("NS-001", "Cloud synchronization is excluded.")]
    draft.out_of_scope[0].text = "DISCARDED_MODEL_TEXT"
    compiler, writer = compiler_and_writer()
    monkeypatch.setattr("backend.services.spec_compiler.complete_with_usage", lambda *a, **kw: draft)
    content = compiler.compile(sheet, None, writer=writer)
    packet = next(call.args[1] for call in writer.write_json.call_args_list if call.args[0] == BLOCKS)
    assert "DISCARDED_MODEL_TEXT" not in str(packet)
    block = next(block for block in packet["blocks"] if block["section"] == "out_of_scope")
    assert block["item_id"] == "LOCKED-NS-001" and block["text"] in content


def test_compiler_repairs_generated_block_with_shared_retry_budget(draft, sheet, monkeypatch):
    from backend.pipeline.builder import _stage
    from backend.infrastructure.stage_retry import CURRENT_RETRY
    bad = deepcopy(draft)
    bad.background[0].item_id = bad.mission[0].item_id
    draft.out_of_scope = []
    responses = iter([bad, draft]); attempts = []
    def complete(*args, **kwargs):
        context = CURRENT_RETRY.get()
        attempts.append((context["attempt"], getattr(context["error"], "block_reason", None)))
        return next(responses)
    compiler, writer = compiler_and_writer()
    monkeypatch.setattr("backend.services.spec_compiler.complete_with_usage", complete)
    result = _stage("spec_compile", lambda state: {"spec": compiler.compile(sheet, None, writer=writer)}, None)({})
    assert "# Final Agent Specification" in result["spec"]
    assert attempts == [(0, None), (1, "duplicate_item_id")]
    assert CURRENT_RETRY.get() is None


def test_compiler_exhausts_existing_budget_without_accepting_invalid_blocks(draft, sheet, monkeypatch):
    from backend.pipeline.builder import _stage
    from backend.infrastructure.stage_retry import CURRENT_RETRY, MAX_RETRIES
    draft.background = []; attempts = []
    def complete(*args, **kwargs):
        attempts.append(CURRENT_RETRY.get()["attempt"])
        return draft
    compiler, writer = compiler_and_writer()
    monkeypatch.setattr("backend.services.spec_compiler.complete_with_usage", complete)
    with pytest.raises(SpecCompilationError):
        _stage("spec_compile", lambda state: {"spec": compiler.compile(sheet, None, writer=writer)}, None)({})
    assert attempts == list(range(MAX_RETRIES + 1))
    assert CURRENT_RETRY.get() is None


def test_discarded_scope_prose_is_not_subject_to_model_language_contract(draft):
    from backend.infrastructure.output_language import language_issues
    draft.out_of_scope[0].text = "앱이 사용하지 않을 모델 비범위 원문"
    assert language_issues(draft) == []
    draft.background[0].text = "생성 본문은 여전히 영어여야 합니다."
    assert "background[0].text: en" in language_issues(draft)


def test_saved_validation_records_bind_explicit_execution_context(draft, sheet, monkeypatch):
    from protocol.logging import log_context
    draft.background[0].requirement_ids = ["PRIVATE_REFERENCE"]
    compiler, writer = compiler_and_writer()
    monkeypatch.setattr("backend.services.spec_compiler.complete_with_usage", lambda *a, **kw: draft)
    with log_context(execution_id="a" * 32):
        with pytest.raises(SpecCompilationError): compiler.compile(sheet, None, writer=writer)
    records = [call.args[1] for call in writer.write_json.call_args_list if call.args[0] == "analysis/spec_compile_validation.json"]
    assert len(records) == 4
    assert all(record["execution_id"] == "a" * 32 and record["validation_reason"] == "unknown_requirement" and record["validation_section"] == "background" and record["validation_index"] == 0 and record["validation_field"] == "requirement_ids" for record in records)
