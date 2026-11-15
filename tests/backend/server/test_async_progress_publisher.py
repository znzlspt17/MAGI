import asyncio
from concurrent.futures import Future
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.infrastructure.progress_publisher import ProgressPublisher


def test_progress_publisher_awaits_db_operations(monkeypatch):
    class Broker:
        def __init__(self, _settings):
            self.ready = Event()
            self.ready.set()
        def publish(self, *_args):
            result = Future()
            result.set_result(True)
            return result
        def close(self):
            pass

    async def scenario():
        monkeypatch.setattr("backend.infrastructure.progress_publisher.Broker", Broker)
        delivered = asyncio.Event()
        publisher = ProgressPublisher(SimpleNamespace(), None)
        async def pending():
            return [] if delivered.is_set() else [{"id": 1, "owner_id": None}]
        async def mark(_id):
            delivered.set()
        publisher.store.pending = AsyncMock(side_effect=pending)
        publisher.store.delivered = AsyncMock(side_effect=mark)
        publisher.wake.set()
        try:
            await asyncio.wait_for(delivered.wait(), 1)
            publisher.store.delivered.assert_awaited_once_with(1)
        finally:
            await publisher.close()
    asyncio.run(scenario())
