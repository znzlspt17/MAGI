"""명세 스냅샷별 번역, 구조 검증, 캐시와 API 언어 선택을 검증한다."""

import asyncio
from copy import deepcopy

import pytest
from websockets.asyncio.server import serve

from backend.config import MagiConfig
from backend.engine import MagiSpecEngine
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.models import CompletionResult, SpecTranslationResponse
from backend.server.app import MagiServer
from backend.server.execution_history import ExecutionHistory
from backend.server.job_manager import JobManager
from backend.services.spec_translation import korean_translation, source_key, _validate, TranslationValidationError
from gateway.app import create_app


ENGLISH = "# Final Agent Specification\n\n## 1. Mission\n\nStore notes for 30 days (REQ-001).\n\n## 2. Implementation\n\nUse `notes.json`.\n\n```js\nconst days = 30;\n```\n"
KOREAN = "# 최종 에이전트 명세\n\n## 1. 목적\n\n메모를 30일 동안 저장합니다 (REQ-001).\n\n## 2. 구현\n\n`notes.json`을 사용합니다.\n\n```js\nconst days = 30;\n```\n"


class TranslationProvider:
    provider_name = "openai"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def create_conversation(self):
        return "conv_translation"

    def complete_result(self, messages, **kwargs):
        self.calls.append((deepcopy(messages), kwargs))
        return CompletionResult(text="", parsed=SpecTranslationResponse(content=next(self.outputs)),
                                response_id=f"resp_translation{len(self.calls)}", input_tokens=100, output_tokens=80)


def make_manager(tmp_path, monkeypatch, outputs):
    provider = TranslationProvider(outputs)
    manager = JobManager(tmp_path, engine_factory=lambda: MagiSpecEngine(config=MagiConfig.default(), provider=provider))
    monkeypatch.setattr(manager, "_submit_locked", lambda *args: None)
    job = manager.create("메모 앱")
    writer = ArtifactWriter(manager.root(job["id"]), allow_overwrite=True)
    writer.write_text("draft/approval_candidate_spec.en.md", ENGLISH)
    history = ExecutionHistory(writer.output_dir)
    history.stage(job["execution_id"], "spec_compile", "started")
    history.stage(job["execution_id"], "spec_compile", "completed")
    history.capture(job["execution_id"], "spec_compile", root=writer.output_dir)
    step_id = history.graph()["nodes"][-1]["id"]
    return manager, provider, job, step_id, writer


def test_translation_repairs_then_caches_each_snapshot_after_restart(tmp_path, monkeypatch):
    manager, provider, job, first_step, writer = make_manager(tmp_path, monkeypatch,
        [KOREAN.replace('REQ-001', 'REQ-002'), KOREAN, KOREAN.replace("30", "60")])
    ident = job["id"]
    try:
        assert manager.document(ident, first_step, "en")["content"] == ENGLISH
        assert len(provider.calls) == 0
        korean = manager.document(ident, first_step, "ko")
        assert korean["content"] == KOREAN
        assert korean["filename"] == "approval_candidate_spec.ko.md"
        assert korean["usage"] is not None
        assert manager.document(ident, first_step, "ko")["content"] == KOREAN
        assert len(provider.calls) == 2
        assert provider.calls[0][1]['conversation_id'] == provider.calls[1][1]['conversation_id']
        assert any('validation_failures' in item['content'] for item in provider.calls[1][0])
        assert writer.read_text("draft/approval_candidate_spec.en.md") == ENGLISH
        writer.write_text("draft/approval_candidate_spec.en.md", ENGLISH.replace("30", "60"))
        assert manager.document(ident, first_step, "ko")["content"] == KOREAN
        history = ExecutionHistory(writer.output_dir)
        history.stage(job["execution_id"], "spec_compile", "started")
        history.stage(job["execution_id"], "spec_compile", "completed")
        history.capture(job["execution_id"], "spec_compile", root=writer.output_dir)
        second_step = history.graph()["nodes"][-1]["id"]
        assert manager.document(ident, second_step, "ko")["content"] == KOREAN.replace("30", "60")
        assert len(provider.calls) == 3
        manager.close()
        manager = JobManager(tmp_path, engine_factory=lambda: MagiSpecEngine(config=MagiConfig.default(), provider=provider))
        assert manager.document(ident, first_step, "ko")["content"] == KOREAN
        assert len(provider.calls) == 3
    finally:
        manager.close()


@pytest.mark.parametrize("translated", [
    KOREAN.replace("const days = 30;", "const days = 31;"),
    KOREAN.replace("## 2.", "### 2."), KOREAN.replace("## 1. 목적", "## 1. Mission"),
    KOREAN.replace("메모를 30일 동안 저장합니다 (REQ-001).", ""), ENGLISH,
])
def test_invalid_translation_cannot_be_cached_or_downloaded(translated):
    with pytest.raises(TranslationValidationError):
        _validate(ENGLISH, translated)


@pytest.mark.parametrize('original,translated,number', [
    ('10ms', '10밀리초', '10'), ('-0.50s', '-0.50초', '-0.50'),
    ('30.', '30', '30'), ('1.2.3.', '1.2.3', '1.2.3'),
])
def test_numeric_values_survive_units_sentence_punctuation_and_korean_word_order(original, translated, number):
    source = f'# Specification\n\nUse {original}' + ('' if original.endswith('.') else '.')
    korean = f'# 명세\n\n값은 {translated}입니다.'
    _validate(source, korean)
    with pytest.raises(TranslationValidationError) as caught:
        _validate(source, korean.replace(number, '99'))
    assert "numbers" in caught.value.failed_checks
    if number.startswith('-'):
        for changed in (number.lstrip('-'), '-0.51'):
            with pytest.raises(TranslationValidationError) as caught:
                _validate(source, korean.replace(number, changed))
            assert 'numbers' in caught.value.failed_checks


@pytest.mark.parametrize('original,translated', [
    ('1-3 days', '1~3일'), ('10-20ms', '10에서 20밀리초'),
    ('-3 to -1', '-3~-1'),
])
def test_numeric_ranges_preserve_endpoints_and_negative_signs(original, translated):
    source = f'# Specification\n\nWait {original}.'
    korean = f'# 명세\n\n대기 범위는 {translated}입니다.'
    _validate(source, korean)
    for changed in (translated.replace('3', '4').replace('20', '21'), translated + ' 99'):
        with pytest.raises(TranslationValidationError) as caught:
            _validate(source, f'# 명세\n\n대기 범위는 {changed}입니다.')
        assert 'numbers' in caught.value.failed_checks


def test_identifier_only_sections_and_final_fence_newline_are_not_english_prose():
    source = ENGLISH + "\n## 3. References\n\n- REQ-001\n"
    korean = KOREAN + "\n## 3. 참조\n\n- REQ-001\n"
    _validate(source, korean)
    _validate(ENGLISH, KOREAN.rstrip("\n"))
    with pytest.raises(TranslationValidationError) as caught:
        _validate(source + "\n## 4. Rule\n\nREQ-001 must remain active.\n",
                  korean + "\n## 4. 규칙\n\nREQ-001 must remain active.\n")
    assert "section_language" in caught.value.failed_checks


def test_korean_particles_preserve_identifier_ranges_and_occurrence_counts():
    source = "# Specification\n\nApply REQ-001 through REQ-009; verify REQ-001."
    korean = "# 명세\n\nREQ-001부터 REQ-009까지 적용하고 REQ-001을 검증합니다."
    _validate(source, korean)
    for changed in (korean.replace("REQ-009", "REQ-008"),
                    korean.replace("REQ-001을", "요구사항을"),
                    korean.replace("REQ-009", "REQ-009extra")):
        with pytest.raises(TranslationValidationError) as caught:
            _validate(source, changed)
        assert "identifiers" in caught.value.failed_checks


def test_failed_translation_keeps_original_and_only_safe_diagnostics(tmp_path, monkeypatch, caplog):
    import json
    from backend.server.diagnostics import diagnose_exception
    marker = 'DO_NOT_RECORD_TRANSLATION_CONTENT'
    manager, provider, job, step_id, writer = make_manager(tmp_path, monkeypatch, [KOREAN.replace("30일", "60일") + marker] * 4)
    try:
        with pytest.raises(TranslationValidationError) as caught:
            manager.document(job["id"], step_id, "ko")
        assert len(provider.calls) == 4
        assert manager.document(job["id"], step_id, "en")["content"] == ENGLISH
        assert not writer.path(f"translations/{source_key(ENGLISH)}/translation.ko.json").exists()
        diagnostic = writer.read_json(f"translations/{source_key(ENGLISH)}/validation.json")
        assert diagnostic["status"] == "failed" and len(diagnostic["attempts"]) == 4
        assert all("numbers" in attempt["failed_checks"] for attempt in diagnostic["attempts"])
        mismatch = diagnostic["attempts"][0]["number_mismatches"][0]
        assert mismatch == {
            'section_index': 2, 'source_section': '1', 'translated_section': '1',
            'source_line': 3, 'translated_line': 3,
            'source_text': '## 1. Mission\n\nStore notes for 30 days (REQ-001).\n\n',
            'translated_text': '## 1. 목적\n\n메모를 60일 동안 저장합니다 (REQ-001).\n\n',
            'missing_numbers': {'30': 1}, 'extra_numbers': {'60': 1},
        }
        assert "'missing_numbers': {'30': 1}" in caplog.text
        assert "'extra_numbers': {'60': 1}" in caplog.text
        assert 'Store notes for 30 days' in caplog.text
        assert '메모를 60일 동안 저장합니다' in caplog.text
        public = diagnose_exception(caught.value)
        assert public['error_code'] == 'SPEC_TRANSLATION_INVALID' and public['error_stage'] == 'spec_translation'
        assert 'numbers' in public['failed_checks'] and '영어 원문은 보존' in public['reason']
        assert marker not in json.dumps(diagnostic) + json.dumps(public) + caplog.text
        assert 'failed_checks' in caplog.text
    finally:
        manager.close()


def test_numeric_diagnostics_locate_unnumbered_sections_and_ignore_code_headings():
    source = '# Specification\n\n```sh\n# 99 code heading\necho 30\n```\n\n## Limits\nUse 10 and 10.\n'
    translated = '# 명세\n\n```sh\n# 99 code heading\necho 30\n```\n\n## 제한\n10을 사용합니다.\n'
    with pytest.raises(TranslationValidationError) as caught:
        _validate(source, translated)
    assert caught.value.number_mismatches == [{
        'section_index': 2, 'source_section': None, 'translated_section': None,
        'source_line': 8, 'translated_line': 8,
        'source_text': '## Limits\nUse 10 and 10.\n',
        'translated_text': '## 제한\n10을 사용합니다.\n',
        'missing_numbers': {'10': 1}, 'extra_numbers': {},
    }]


@pytest.mark.parametrize("failure", ["provider", "conversation"])
def test_translation_never_repeats_uncertain_provider_failures(tmp_path, failure):
    from backend.errors import MagiError
    class Provider(TranslationProvider):
        def create_conversation(self):
            if failure == "conversation":
                self.calls.append("conversation")
                raise MagiError("OpenAI conversation creation failed.")
            return super().create_conversation()
        def complete_result(self, messages, **kwargs):
            self.calls.append("provider")
            raise MagiError("OpenAI request failed.")
    provider = Provider([])
    with pytest.raises(MagiError):
        korean_translation(ENGLISH, writer=ArtifactWriter(tmp_path), provider=provider, model="gpt-6-luna")
    assert len(provider.calls) == 1


def test_unsupported_document_language_rejected(tmp_path, monkeypatch):
    language = "ja"
    manager, provider, job, step_id, _ = make_manager(tmp_path, monkeypatch, [])
    try:
        with pytest.raises(ValueError):
            manager.document(job["id"], step_id, language)
        assert not provider.calls
    finally:
        manager.close()


def test_document_gateway_and_backend_transport(tmp_path, monkeypatch):
    manager, provider, job, step_id, _ = make_manager(tmp_path, monkeypatch, [KOREAN])

    async def scenario():
        server = MagiServer(tmp_path / "unused")
        server.manager.close()
        server.manager = manager
        async with serve(server.handler, "127.0.0.1", 0) as socket_server:
            port = socket_server.sockets[0].getsockname()[1]

            def request():
                app = create_app({"MAGI_PUBLIC_MODE": False, "TESTING": True, "MAGI_SERVER_URL": f"ws://127.0.0.1:{port}"})
                with app.test_client() as client:
                    url = f'/api/jobs/{job["id"]}/steps/{step_id}/document'
                    assert client.post(url, json={"language": []}).status_code == 400
                    for language, content in (("ko", KOREAN), ("en", ENGLISH)):
                        response = client.post(url, json={"language": language})
                        assert response.status_code == 200
                        assert response.json["content"] == content
                        assert response.json["language"] == language
                    assert client.post(f'/api/jobs/{job["id"]}/steps/missing/document', json={"language": "ko"}).status_code == 404

            await asyncio.to_thread(request)

    try:
        asyncio.run(scenario())
        assert len(provider.calls) == 1
    finally:
        manager.close()


def test_translation_failure_has_readable_message_over_document_transport(tmp_path, monkeypatch):
    manager, provider, job, step_id, _ = make_manager(tmp_path, monkeypatch, [KOREAN.replace("30일", "60일")] * 4)
    async def scenario():
        server = MagiServer(tmp_path / "unused")
        server.manager.close()
        server.manager = manager
        async with serve(server.handler, "127.0.0.1", 0) as socket_server:
            port = socket_server.sockets[0].getsockname()[1]
            def request():
                app = create_app({"MAGI_PUBLIC_MODE": False, "TESTING": True, "MAGI_SERVER_URL": f"ws://127.0.0.1:{port}"})
                with app.test_client() as client:
                    url = f'/api/jobs/{job["id"]}/steps/{step_id}/document'
                    response = client.post(url, json={"language": "ko"})
                    assert response.status_code == 502
                    assert "영어 원문은 보존" in response.json["error"]
                    assert client.post(url, json={"language": "en"}).json["content"] == ENGLISH
            await asyncio.to_thread(request)
    try:
        asyncio.run(scenario())
        assert len(provider.calls) == 4
        assert manager.get(job["id"])["status"] == "queued"
    finally:
        manager.close()
