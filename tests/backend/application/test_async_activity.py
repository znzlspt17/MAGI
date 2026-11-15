"""비동기 부가 작업의 저장 완료와 취소를 활동으로 추적한다."""

import asyncio

import pytest

from backend.application.activity import tracked


def test_activity_remains_tracked_until_async_save_finishes_and_cancellation_cleans_up():
    class Service:
        def __init__(self):
            self.lock = asyncio.Lock()
            self._activities = {}
            self.saved = asyncio.Event()

        async def get(self, ident):
            return {"id": ident}

        @tracked
        async def save(self, ident):
            assert self._activities[ident] == 1
            await self.saved.wait()
            return "saved"

    async def scenario():
        service = Service()
        task = asyncio.create_task(service.save("job"))
        try:
            await asyncio.sleep(0)
            assert service._activities["job"] == 1
            assert not task.done()
            service.saved.set()
            assert await task == "saved"
            assert service._activities["job"] == 0
            service.saved.clear()
            task = asyncio.create_task(service.save("job"))
            await asyncio.sleep(0)
            assert service._activities["job"] == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert service._activities["job"] == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_activity_tracks_pending_lookup_and_cleans_up_when_lookup_fails():
    class Service:
        def __init__(self):
            self.lock = asyncio.Lock()
            self._activities = {}
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
        async def get(self, ident):
            self.entered.set()
            await self.release.wait()
            raise KeyError(ident)
        @tracked
        async def work(self, ident):
            raise AssertionError('invalid job must not run')
    async def scenario():
        service = Service()
        task = asyncio.create_task(service.work('job'))
        await service.entered.wait()
        assert service._activities['job'] == 1
        service.release.set()
        with pytest.raises(KeyError):
            await task
        assert service._activities['job'] == 0
    asyncio.run(scenario())
