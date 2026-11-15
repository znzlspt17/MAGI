"""계정 연결 후 기존 익명 프로젝트의 조회 권한."""

import asyncio
from contextlib import asynccontextmanager

from backend.access.context import ACTOR
from backend.knowledge.config import KnowledgeConfig
from backend.knowledge.project_decisions import ProjectDecisionStore
from backend.knowledge.store import KnowledgeStore


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    async def execute(self, sql, params=()):
        projects = [{"id": "p1", "name": "익명 작업", "owner_id": "guest"}]
        if "WHERE owner_id=%s" in sql:
            projects = [project for project in projects if project["owner_id"] == params[0]]
        elif "WHERE owner_id=ANY(%s)" in sql:
            projects = [project for project in projects if project["owner_id"] in params[0]]
        return _Cursor(projects)


def test_linked_account_can_list_and_use_guest_project():
    async def run():
        store = KnowledgeStore(KnowledgeConfig({}))
        conn = _Connection()

        @asynccontextmanager
        async def transaction(*, mode="write"):
            yield conn

        store.transaction = transaction
        token = ACTOR.set({"id": "google", "owner_ids": ["google", "guest"]})
        try:
            projects = await store.projects()
            assert [project["id"] for project in projects] == ["p1"]
            assert (await ProjectDecisionStore(store).require_project(conn, "p1"))["id"] == "p1"
        finally:
            ACTOR.reset(token)

    asyncio.run(run())
