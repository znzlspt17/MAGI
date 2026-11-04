"""MCP 참고자료는 출처를 보존하며 정상 JSON으로 제한한다."""

import json

from backend.mcp_client.context import bounded_results


def test_context_is_valid_bounded_json_with_provenance():
    document = {"results": [{"connection_id": "conn", "connection_version": 2, "tool_name": "search",
                             "schema_hash": "a" * 64, "arguments_hash": "b" * 64,
                             "status": "ok", "text": '"문서\\' * 5000}]}
    encoded, fingerprint = bounded_results(document)
    assert len(encoded) <= 8000 and len(fingerprint) == 64
    item = json.loads(encoded)["results"][0]
    assert item["connection_id"] == "conn" and item["tool_name"] == "search"
    assert item["schema_hash"] == "a" * 64 and item["arguments_hash"] == "b" * 64


def test_failed_and_unidentified_results_are_not_presented_as_evidence():
    assert bounded_results({"results": [{"status": "error", "text": "error"},
                                          {"status": "ok", "text": "missing provenance"}]}) is None


def test_identical_mcp_context_is_sent_only_once_per_conversation(store, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from pydantic import BaseModel
    from backend.infrastructure.provider_call import _complete_connected
    from backend.knowledge.core import Documents
    from backend.models import CompletionResult

    class Output(BaseModel):
        value: str

    project = store.create_project("MCP 문맥")
    store.save_job({"id": "mcp-context-job", "project_id": project["id"], "request": "example"})
    writer = Documents(store, "mcp-context-job")
    writer.write_json("research/mcp_results.json", {"results": [{"connection_id": "c1", "tool_name": "find",
        "schema_hash": "s1", "arguments_hash": "a1", "status": "ok", "text": "공식 자료"}]})
    fake = SimpleNamespace(provider_name="openai", complete_result=Mock(return_value=CompletionResult(
        text="", parsed=Output(value="ok"), response_id="resp_test")))
    monkeypatch.setattr("backend.infrastructure.provider_call.prepare_context", lambda w, m, s:
                        (m, SimpleNamespace(restore=lambda value: value)))
    monkeypatch.setitem(__import__("backend.infrastructure.provider_call", fromlist=["STAGE_SCHEMAS"]).STAGE_SCHEMAS, "spec_compile", Output)
    kwargs = {"model": "gpt-6-luna", "stage": "spec_compile", "temperature": 0,
              "isolated_schema": None, "conversation_id": "conv_test"}
    _complete_connected(writer, fake, [], **kwargs)
    _complete_connected(writer, fake, [], **kwargs)
    first, second = [call.args[0] for call in fake.complete_result.call_args_list]
    assert any("External MCP reference data:" in item.get("content", "") for item in first)
    assert not any("External MCP reference data:" in item.get("content", "") for item in second)
