"""문서 조회 후 작업 명령과 안전한 충돌 응답을 검증한다."""

import pytest

from backend.server.app import Server
from backend.server.cleanup import CleanupConflict
from backend.server.diagnostics import safe_user_error
from tests.support.workflow_helpers import manager_for


def test_message_after_document_read_needs_no_provider_and_can_be_sent(store, monkeypatch):
    manager, _ = manager_for(store, monkeypatch)
    server = object.__new__(Server)
    server.manager = manager
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        execution = manager.get(ident)["execution_id"]
        monkeypatch.setattr(manager.workspace._documents, "step", lambda *args: {
            "document": {"content": "저장된 한국어 명세입니다.", "filename": "SPEC.ko.md"},
        })
        def reject_engine(*args, **kwargs):
            pytest.fail("원본 문서 조회에서 모델을 호출해서는 안 됩니다")
        monkeypatch.setattr(manager.workspace._documents, "engine", reject_engine)
        command = {"method": "message", "params": {
            "id": ident, "execution_id": execution, "payload": "보관 기간은 30일로 정해주세요.",
        }}
        document = manager.workspace.document(ident, "spec")
        assert document["content"] == "저장된 한국어 명세입니다."
        assert document["language"] == "ko"
        assert manager.get(ident)["execution_id"] == execution
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        result = server._dispatch_request(command)
        assert result["status"] == "queued"
        assert result["execution_id"] != execution
        assert manager._submit_locked.call_args.args[1:] == ("message", command["params"]["payload"])
    finally:
        manager.close()


@pytest.mark.parametrize("message", [
    "작업 상태가 바뀌었습니다. 최신 대화를 확인하세요.",
    "이전 작업의 처리가 마무리되고 있습니다. 잠시 후 다시 시도해주세요.",
])
def test_known_command_conflicts_preserve_actionable_message(message):
    assert safe_user_error(CleanupConflict(message)) == message


def test_unrecognized_conflict_does_not_expose_exception_text():
    assert safe_user_error(CleanupConflict("UNTRUSTED_RESPONSE_TEXT")) == "작업 처리 중 오류가 발생했습니다."
