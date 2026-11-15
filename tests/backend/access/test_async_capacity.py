import asyncio

import pytest

from backend.access.capacity import ExecutionCapacity
from backend.access.context import AccessError


def test_capacity_waits_without_blocking_event_loop_and_cancellation_releases_slot():
    async def scenario():
        capacity = ExecutionCapacity()
        entered = asyncio.Event()
        release = asyncio.Event()
        async def work():
            async with capacity.slot(blocking=True):
                entered.set()
                await release.wait()
        task = asyncio.create_task(work())
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert capacity.active == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert capacity.active == 0
        async with capacity.maintenance():
            with pytest.raises(AccessError):
                await capacity.check_admission()
    asyncio.run(scenario())
