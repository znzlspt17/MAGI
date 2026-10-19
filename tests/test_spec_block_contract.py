"""본문 단일 생성 계약과 실제 SDK 직렬화·원문 연결 경계를 검증한다."""

import json

import httpx2
import pytest

from backend.config import MagiConfig
from backend.errors import SpecCompilationError
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.output_language import language_issues
from backend.models import SpecDraftResponse, assemble_spec_draft, RequirementLockSheet, STAGE_SCHEMAS
from backend.providers.llm_provider import OpenAIProvider
from backend.services.skill_registry import SkillRegistry
from backend.services.spec_compiler import SpecCompiler, _rendered_sections
from test_conversation_structured import transport, packet


def draft():
    return {name: [{"item_id": "BLOCK-" + name, "text": "Store notes locally.",
                    "requirement_ids": ["REQ-001"] if name == "architecture" else [], "decision_ids": []}]
            for name in SpecDraftResponse.model_fields if name != "decisions"} | {"decisions": []}


def locked():
    return RequirementLockSheet.from_dict({"workflow_constraints": [], "mandatory_requirements": [
        {"id": "REQ-001", "text": "Store notes locally.", "source": "user_request"}],
        "constraints": [{"id": "CON-001", "text": "Never delete retained notes.", "source": "user_request"}],
        "non_scope": [{"id": "NS-001", "text": "Cloud synchronization is excluded.", "source": "user_request"}]})


def test_sdk_wire_generates_text_once_and_server_persists_exact_quotes(tmp_path):
    calls = []
    value = draft()
    value["forbidden_behaviors"][0].update(text="Never delete retained notes.  \n\n", requirement_ids=["CON-001"])
    value["out_of_scope"][0]["text"] = "The server must use the canonical locked non-scope."
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx2.Response(200, json=packet(value))
    writer = ArtifactWriter(tmp_path)
    compiler = SpecCompiler(config=MagiConfig.default(), provider=OpenAIProvider(api_key="fake-test-value"),
                            skills=SkillRegistry(), evidence=None)
    with transport(handle):
        spec = compiler.compile(locked(), {}, user_request="메모", writer=writer)
    assert len(calls) == 1
    schema = calls[0]["text"]["format"]["schema"]
    assert STAGE_SCHEMAS["spec_compile"] is SpecDraftResponse
    assert "spec_links" not in schema["properties"]
    assert schema["properties"]["forbidden_behaviors"]["type"] == "array"
    assert "quote" not in schema["$defs"]["SpecBlock"]["properties"]
    trace = writer.read_json("analysis/spec_trace.json")
    sections = _rendered_sections(spec)
    assert all(link["quote"] in sections[link["section"]] for link in trace["links"])
    assert any(link["section"] == "forbidden_behaviors" for link in trace["links"])
    assert any(link["item_id"] == "LOCKED-NS-001" for link in trace["links"])
    assert "The server must use the canonical locked non-scope." not in spec


@pytest.mark.parametrize("change", ["unknown_reference", "duplicate_id", "empty_text", "fixed_heading"])
def test_block_contract_keeps_semantic_and_identity_validation(change):
    value = draft()
    block = value["architecture"][0]
    if change == "unknown_reference": block["requirement_ids"] = ["REQ-MISSING"]
    if change == "duplicate_id": block["item_id"] = value["mission"][0]["item_id"]
    if change == "empty_text": block["text"] = " "
    if change == "fixed_heading": block["text"] = "### Locked Constraints\nDo something else."
    with pytest.raises(SpecCompilationError):
        assemble_spec_draft(SpecDraftResponse.model_validate(value), locked())


def test_block_language_and_multiline_source_are_preserved():
    value = draft()
    value["architecture"][0]["text"] = "Store notes\n  locally.\n\n## Storage details\nKeep versions."
    model = SpecDraftResponse.model_validate(value)
    assert not language_issues(model)
    spec = assemble_spec_draft(model, locked())
    assert next(link for link in spec.spec_links if link.section == "architecture").quote == value["architecture"][0]["text"]
    value["architecture"][0]["text"] = "한국어 본문"
    assert language_issues(SpecDraftResponse.model_validate(value)) == ["architecture[0].text: en"]
