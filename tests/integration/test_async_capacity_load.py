"""DB 연결 수와 별개인 AI 실행 슬롯의 비동기 부하 경계."""

import asyncio

from backend.access.capacity import ExecutionCapacity


def test_one_hundred_executions_overlap_and_overflow_waits_without_blocking_loop():
    async def scenario():
        capacity = ExecutionCapacity()
        release = asyncio.Event()
        started = asyncio.Event()
        overflow_started = asyncio.Event()
        entered = 0

        async def execute():
            nonlocal entered
            async with capacity.slot(blocking=True):
                entered += 1
                if entered == 100:
                    started.set()
                await release.wait()

        async def overflow():
            async with capacity.slot(blocking=True):
                overflow_started.set()

        tasks = [asyncio.create_task(execute()) for _ in range(100)]
        extra = None
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            assert capacity.active == 100
            extra = asyncio.create_task(overflow())
            await asyncio.sleep(0.02)
            assert not overflow_started.is_set()
            assert all(not task.done() for task in tasks)
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks, extra), timeout=3)
            assert overflow_started.is_set()
            assert capacity.active == 0
        finally:
            release.set()
            for task in [*tasks, *([extra] if extra else [])]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, *([extra] if extra else []), return_exceptions=True)

    asyncio.run(scenario())


def test_cancelled_execution_releases_slot_and_does_not_cancel_other_executions():
    async def scenario():
        capacity = ExecutionCapacity()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def execute():
            async with capacity.slot(blocking=True):
                entered.set()
                await release.wait()

        task = asyncio.create_task(execute())
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            assert capacity.active == 1
            task.cancel()
            result = await asyncio.gather(task, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert capacity.active == 0
            async with capacity.slot(blocking=False):
                assert capacity.active == 1
            assert capacity.active == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
