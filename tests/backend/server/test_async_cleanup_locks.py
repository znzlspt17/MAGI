import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from backend.server.cleanup import Cleanup
from backend.server.job_manager import JobManager


def test_cleanup_does_not_hold_manager_lock_while_waiting_for_database():
    async def scenario():
        waiting = asyncio.Event()
        class Store:
            @asynccontextmanager
            async def transaction(self, **_kwargs):
                waiting.set()
                await asyncio.Event().wait()
                yield self
        manager = JobManager(SimpleNamespace(store=Store()))
        ident = "a" * 32
        manager.jobs[ident] = {"id": ident, "status": "queued"}
        cleanup = Cleanup(manager)
        task = asyncio.create_task(cleanup.preview({"scope": "all"}))
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            async with asyncio.timeout(.2):
                assert (await manager.get(ident))["status"] == "queued"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
