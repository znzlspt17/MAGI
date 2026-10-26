"""문서 번역 중 명령 거부 사유와 번역 종료 후 재접수를 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from backend.access.context import AccessError
from backend.server.app import Server
from backend.server.cleanup import CleanupConflict
from backend.server.diagnostics import safe_user_error
from test_workflow import manager_for


def test_message_during_translation_has_safe_conflict_and_can_be_sent_afterwards(store, monkeypatch):
    import backend.server.workspace as workspace

    manager, _ = manager_for(store, monkeypatch)
    entered, finish = Event(), Event()
    server = object.__new__(Server)
    server.manager = manager
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        execution = manager.get(ident)["execution_id"]
        monkeypatch.setattr(manager.workspace, "step", lambda *args: {
            "document": {"content": "Saved English specification.", "filename": "SPEC.en.md"},
        })
        monkeypatch.setattr(manager.workspace, "engine", lambda *args, **kwargs: SimpleNamespace(
            provider=None, config=SimpleNamespace(model_routing={"compiler": SimpleNamespace(model="fake")}),
        ))

        def translate(*args, **kwargs):
            entered.set()
            assert finish.wait(10)
            return {"content": "저장된 명세", "language": "ko"}

        monkeypatch.setattr(workspace, "korean_translation", translate)
        command = {"method": "message", "params": {
            "id": ident, "execution_id": execution, "payload": "보관 기간은 30일로 정해주세요.",
        }}
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(manager.workspace.document, ident, "spec", "ko")
            try:
                assert entered.wait(5)
                with pytest.raises(AccessError) as caught:
                    server._dispatch_request(command)
                assert caught.value.code == "conflict"
                assert str(caught.value) == "문서 번역이 진행 중입니다. 번역이 끝난 뒤 다시 보내주세요."
                assert manager.get(ident)["execution_id"] == execution
                assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
            finally:
                finish.set()
            assert future.result(timeout=5)["language"] == "ko"
        result = server._dispatch_request(command)
        assert result["status"] == "queued"
        assert result["execution_id"] != execution
        assert manager._submit_locked.call_args.args[1:] == ("message", command["params"]["payload"])
    finally:
        finish.set()
        manager.close()


@pytest.mark.parametrize("message", [
    "작업 상태가 바뀌었습니다. 최신 대화를 확인하세요.",
    "이전 작업의 처리가 마무리되고 있습니다. 잠시 후 다시 시도해주세요.",
])
def test_known_command_conflicts_preserve_actionable_message(message):
    assert safe_user_error(CleanupConflict(message)) == message


def test_unrecognized_conflict_does_not_expose_exception_text():
    assert safe_user_error(CleanupConflict("UNTRUSTED_RESPONSE_TEXT")) == "작업 처리 중 오류가 발생했습니다."
