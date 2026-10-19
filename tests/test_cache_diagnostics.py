import json
from unittest.mock import patch, MagicMock

import pytest

from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.provider_call import complete_with_usage
from backend.infrastructure.cache_diagnostics import safe_diagnostics, safe_response_id
from backend.providers.llm_provider import OpenAIProvider
from backend.errors import MagiError


def response(identifier="resp_first", diagnostic=None):
    return {"id": identifier, "output_text": "OK", "usage": {
        "input_tokens": 2000, "output_tokens": 1,
        "input_tokens_details": {"cached_tokens": 1024}},
        "prompt_cache_diagnostics": diagnostic}


def network(data):
    context = MagicMock()
    result = context.return_value.__enter__.return_value.responses.create.return_value
    result.status = "completed"
    result.output_text = data["output_text"]
    result.model_dump.return_value = data
    return context


def invoke(writer, provider=None, stage="compile", model="gpt-6-luna"):
    return complete_with_usage(writer, provider or OpenAIProvider(api_key="fake-test-value"),
                               [{"role": "user", "content": "DO_NOT_RECORD_PROMPT"}],
                               stage=stage, model=model)


def test_baseline_restore_isolation_and_failure(tmp_path, caplog):
    writer = ArtifactWriter(tmp_path / "one")
    diagnostic = {"type": "cache_miss", "reason": "input_changed", "cache_missed_tokens": 100}
    with patch("backend.providers.llm_provider.OpenAI", new=network(response())) as call:
        assert invoke(writer) == "OK"
        assert "comparison_response_id" not in call.return_value.__enter__.return_value.responses.create.call_args.kwargs["prompt_cache_options"]
    with patch("backend.providers.llm_provider.OpenAI", side_effect=RuntimeError("fake failure")):
        with pytest.raises(RuntimeError):
            invoke(writer)
    caplog.set_level("INFO", logger="backend.server")
    with patch("backend.providers.llm_provider.OpenAI", new=network(response("resp_second", diagnostic))) as call:
        invoke(ArtifactWriter(tmp_path / "one"))
        assert call.return_value.__enter__.return_value.responses.create.call_args.kwargs["prompt_cache_options"]["comparison_response_id"] == "resp_first"
    stored = writer.read_json("state/provider_usage.json")
    last = stored["attempts"][-1]
    assert last["cache_diagnostics"]["reason"] == "input_changed"
    assert last["comparison_elapsed_ms"] >= 0
    assert last["started_at"].endswith("+00:00")
    assert stored["attempts"][0]["response_id"] == "resp_first"
    assert "DO_NOT_RECORD_PROMPT" not in json.dumps(stored) + caplog.text
    assert "resp_second" not in caplog.text
    for target, stage, model in [(writer, "critic", "gpt-6-luna"),
                                  (ArtifactWriter(tmp_path / "two"), "compile", "gpt-6-luna")]:
        with patch("backend.providers.llm_provider.OpenAI", new=network(response())) as call:
            invoke(target, stage=stage, model=model)
            assert "comparison_response_id" not in call.return_value.__enter__.return_value.responses.create.call_args.kwargs["prompt_cache_options"]


def test_untrusted_fields_and_old_record(tmp_path):
    assert safe_response_id("resp_bad\nvalue") is None
    assert safe_response_id("resp_" + "x" * 124) is None
    assert safe_diagnostics(None) is None
    assert safe_diagnostics([])["type"] == "unknown"
    value = safe_diagnostics({"type": [], "reason": {"secret": "DO_NOT_RECORD"},
                              "cache_missed_tokens": True, "comparison_reusable_tokens": -1})
    assert value == {"type": "unknown", "reason": "unknown", "cache_missed_tokens": None,
                     "comparison_reusable_tokens": None}
    writer = ArtifactWriter(tmp_path)
    writer.write_json("state/provider_usage.json", {"attempts": [{"stage": "compile", "provider": "openai",
                      "model": "gpt-6-luna", "status": "success"}]})
    with patch("backend.providers.llm_provider.OpenAI", new=network(response())) as call:
        invoke(writer)
        assert "comparison_response_id" not in call.return_value.__enter__.return_value.responses.create.call_args.kwargs["prompt_cache_options"]
    assert writer.read_json("state/provider_usage.json")["attempts"][0]["response_id"] is None


def test_unsupported_cache_model():
    with patch("backend.providers.llm_provider.OpenAI", new=network(response())) as call:
        with pytest.raises(MagiError,match='gpt-6-luna'):
            OpenAIProvider(api_key="fake-test-value").complete_result([], model="gpt-5", comparison_response_id="resp_before")
        call.assert_not_called()
