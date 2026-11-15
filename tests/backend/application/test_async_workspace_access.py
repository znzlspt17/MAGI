"""기존 작업의 물리 소유자를 유지하면서 연결 계정으로 비동기 조회한다."""

from types import SimpleNamespace

import pytest

from backend.access.context import ACTOR
from backend.access.store import AccessStore
from backend.application.workspace_access import WorkspaceAccess
from tests.backend.application.async_helpers import run_async


@run_async
async def test_linked_account_reads_existing_document_but_unrelated_guest_cannot(async_store_factory):
    async with async_store_factory() as store:
        access = AccessStore(store)
        guest_sid = await access.guest()
        guest = await access.session(guest_sid)
        account_sid = await access.login("existing-account", "fake-test-pepper")
        account = await access.session(account_sid)
        outsider = await access.session(await access.guest())
        workspace = WorkspaceAccess(SimpleNamespace(store=store), engine_factory=None)
        job = {"id": "b" * 32, "project_id": "b" * 32, "request": "문서 보관",
               "execution_id": "first", "owner_id": guest["id"], "action": "generate"}
        token = ACTOR.set(guest)
        try:
            await store.accept_job(job, job["request"])
            documents = await workspace.documents(job["id"])
            await documents.write_text("draft/SPEC.md", "저장된 원본")
        finally:
            ACTOR.reset(token)

        linked = await access.session(await access.login("existing-account", "fake-test-pepper", guest_sid))
        assert linked["id"] == account["id"]
        token = ACTOR.set(linked)
        try:
            loaded = await workspace.get(job["id"])
            assert loaded["owner_id"] == guest["id"]
            assert await workspace.read_text(job["id"], "draft/SPEC.md") == "저장된 원본"
        finally:
            ACTOR.reset(token)
        token = ACTOR.set(outsider)
        try:
            with pytest.raises(KeyError):
                await workspace.documents(job["id"])
        finally:
            ACTOR.reset(token)
