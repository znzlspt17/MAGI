"""비동기 작업 사이에서 관리자 잠금이 재진입과 취소를 안전하게 처리한다."""

import asyncio

from backend.server import job_manager


def test_lock_is_reentrant_only_for_its_own_task():
    async def scenario():
        lock = job_manager.AsyncRLock()
        waiting = asyncio.Event()
        entered = asyncio.Event()

        async def other():
            waiting.set()
            async with lock:
                entered.set()

        async with lock:
            async with lock:
                task = asyncio.create_task(other())
                await waiting.wait()
                await asyncio.sleep(0)
                assert not entered.is_set()
            assert not entered.is_set()
        await asyncio.wait_for(task, 1)
        assert entered.is_set()

    asyncio.run(scenario())


def test_cancelled_waiter_does_not_prevent_next_task():
    async def scenario():
        lock = job_manager.AsyncRLock()
        async with lock:
            waiter = asyncio.create_task(lock.acquire())
            await asyncio.sleep(0)
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        await asyncio.wait_for(lock.acquire(), 1)
        lock.release()

    asyncio.run(scenario())
