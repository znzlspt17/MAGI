"""체크포인트와 저널을 네이티브 비동기 DB로 보존한다."""
import asyncio
import sys

from backend.infrastructure.workflow_store import workflow_store


def test_journal_persists_and_releases_pool_between_operations(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            async with workflow_store(store, "job") as (saver, journal):
                assert saver.conn is store._async_pool
                await journal.begin("task")
                await journal.progress("task", 1)
                await journal.response("task", "response")
                await journal.complete("task", {"result": "done"})
                assert await journal.status("task") == "completed"
                assert (await journal.get("task"))["result"] == "done"
                assert (await journal.get("task"))["response_ids"] == ["response"]
                assert store._async_pool.get_stats()["pool_available"] == store._async_pool.get_stats()["pool_size"]
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None) as runner:
        runner.run(scenario())
