import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from backend.access.service import PublicService


def test_concurrent_progress_lists_release_connection_before_checkpoint_lookup():
    async def scenario():
        pool = asyncio.Semaphore(8)
        all_queries = asyncio.Event()
        count = 0

        class Cursor:
            async def fetchall(self):
                nonlocal count
                count += 1
                if count == 8: all_queries.set()
                await all_queries.wait()
                return []

        class Store:
            @asynccontextmanager
            async def transaction(self, **kwargs):
                async with pool:
                    yield self
            async def execute(self, sql): return Cursor()

        store = Store()
        class Access:
            async def session(self, sid):
                return {'id': 'owner', 'owner_ids': ['owner'], 'role': 'user', 'csrf': 'csrf'}
            async def throttle(self, ident): pass
        class Workspace:
            async def summary(self, ident):
                async with store.transaction(mode='read'):
                    return {'id': ident}
        class Manager:
            workspace = Workspace()
            async def ids(self): return ['job']

        service = object.__new__(PublicService)
        service.store = store
        service.access = Access()
        service.manager = Manager()
        request = {'method': 'progress.list', 'params': {}, 'session': 'session'}
        results = await asyncio.wait_for(asyncio.gather(*(service.invoke(request, None) for _ in range(8))), 1)
        assert all(result['jobs'] == [{'id': 'job'}] for result in results)

    asyncio.run(scenario())
