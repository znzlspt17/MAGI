"""실제 PostgreSQL wire 연결을 통한 비동기 실행 이력 저장."""
import asyncio
import sys

from backend.infrastructure.history_repository import HistoryRepository


def test_empty_execution_history_can_be_loaded(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project("history")
            async with store.transaction() as conn:
                await conn.execute("INSERT INTO jobs(id,project_id,data) VALUES (%s,%s,%s)",
                                   ("history-job", project["id"], store._json({"request": "input"})))
            repo = HistoryRepository(store.documents("history-job"), lambda *_: None)
            result = await repo.load()
            assert result["nodes"] == [] and result["executions"] == []

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None) as runner:
        runner.run(scenario())
