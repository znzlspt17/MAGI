"""워크플로 실행 용량과 작업 태스크의 종료 경계."""

import asyncio
from contextlib import asynccontextmanager
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.server.job_manager import JobManager
from backend.server.cleanup import CleanupConflict


def test_close_waits_for_running_work_before_closing_storage():
    async def scenario():
        knowledge = SimpleNamespace(store=SimpleNamespace(), close=AsyncMock())
        manager = JobManager(knowledge)
        entered, release = asyncio.Event(), asyncio.Event()
        finished = []

        async def run(*args, **kwargs):
            entered.set()
            await release.wait()
            finished.append(True)

        manager._run = run
        manager._submit_locked("a", "generate", None)
        await entered.wait()
        closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0)
        assert not closing.done()
        assert not knowledge.close.await_count
        release.set()
        await closing
        assert finished == [True]
        knowledge.close.assert_awaited_once()

    asyncio.run(scenario())


def test_manager_runs_100_jobs_and_releases_the_next_slot(monkeypatch):
    async def scenario():
        monkeypatch.setattr("backend.server.cleanup.Cleanup.recover", AsyncMock())
        knowledge = SimpleNamespace(
            store=SimpleNamespace(jobs=AsyncMock(return_value=[])),
            close=AsyncMock(),
        )
        manager = await JobManager.build(knowledge)
        gate = asyncio.Event()
        hundred_running = asyncio.Event()
        active, maximum = 0, 0

        async def run(_ident, _action, _payload, **_kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            if active == 100:
                hundred_running.set()
            await gate.wait()
            active -= 1

        manager._run = run
        for number in range(101):
            manager._submit_locked(f"{number:032x}", "generate", "test")
        await asyncio.wait_for(hundred_running.wait(), 5)
        assert active == 100 and maximum == 100
        gate.set()
        await asyncio.gather(*list(manager._futures))
        assert maximum == 100
        await manager.close()

    asyncio.run(scenario())


def test_different_jobs_do_not_share_the_same_execution_lock():
    async def scenario():
        manager = JobManager(SimpleNamespace(store=SimpleNamespace()))
        acquired = asyncio.Event()
        async def other_job():
            async with manager.job_lock("b"):
                acquired.set()
        async with manager.job_lock("a"):
            task = asyncio.create_task(other_job())
            await asyncio.wait_for(acquired.wait(), 1)
        await task
    asyncio.run(scenario())


def test_inflight_admissions_count_towards_200_limit():
    async def scenario():
        manager = JobManager(SimpleNamespace(store=SimpleNamespace()))
        gate = asyncio.Event()
        entered = 0
        ready = asyncio.Event()
        async def create(*_args, **_kwargs):
            nonlocal entered
            entered += 1
            if entered == 200:
                ready.set()
            await gate.wait()
            return {"id": "job"}
        manager._create = create
        tasks = [asyncio.create_task(manager.create("input")) for _ in range(200)]
        try:
            await asyncio.wait_for(ready.wait(), 2)
            with pytest.raises(CleanupConflict, match="대기열"):
                await manager.create("extra")
        finally:
            gate.set()
            await asyncio.gather(*tasks)
        assert manager._pending_admissions == 0
    asyncio.run(scenario())


def test_inflight_actions_share_the_admission_limit():
    async def scenario():
        manager = JobManager(SimpleNamespace(store=SimpleNamespace()))
        gate = asyncio.Event()
        ready = asyncio.Event()
        entered = 0
        async def action(*_args, **_kwargs):
            nonlocal entered
            entered += 1
            if entered == 200:
                ready.set()
            await gate.wait()
            return {"id": "job"}
        manager._action_locked = action
        tasks = [asyncio.create_task(manager.action(str(number), "answer", {})) for number in range(200)]
        try:
            await asyncio.wait_for(ready.wait(), 2)
            with pytest.raises(CleanupConflict, match="대기열"):
                await asyncio.wait_for(manager.action("extra", "answer", {}), .2)
        finally:
            gate.set()
            await asyncio.gather(*tasks)
    asyncio.run(scenario())


def test_cancelled_action_restores_original_in_memory_job():
    async def scenario():
        started = asyncio.Event()
        async def record(*_args):
            started.set()
            await asyncio.Event().wait()
        store = SimpleNamespace(record_action=record)
        manager = JobManager(SimpleNamespace(store=store))
        manager.workspace.allowed = AsyncMock(return_value=["answer"])
        ident = "a" * 32
        original = {"id": ident, "status": "NEEDS_USER_INPUT", "execution_id": "old", "order": 1}
        manager.jobs[ident] = original.copy()
        task = asyncio.create_task(manager.action(ident, "answer", {}, expected_execution_id="old"))
        await asyncio.wait_for(started.wait(), 1)
        assert manager.jobs[ident]["status"] == "queued"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert manager.jobs[ident] == original
        assert manager._pending_admissions == 0
    asyncio.run(scenario())


def test_cancelled_create_does_not_publish_uncommitted_job(monkeypatch):
    async def scenario():
        started, rolled_back = asyncio.Event(), []
        class Store:
            @asynccontextmanager
            async def transaction(self):
                try:
                    yield self
                except BaseException:
                    rolled_back.append(True)
                    raise
            async def accept_job(self, job, _request):
                job["reused_decisions"] = []
        manager = JobManager(SimpleNamespace(store=Store()))
        manager.workspace._validate_reuse_sources = AsyncMock()
        manager.workspace.documents = AsyncMock(return_value=object())
        class History:
            def __init__(self, _docs):
                pass
            async def start_execution(self, *_args, **_kwargs):
                started.set()
                await asyncio.Event().wait()
        monkeypatch.setattr("backend.server.job_manager.ExecutionHistory", History)
        task = asyncio.create_task(manager.create("input"))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not manager.jobs
        assert rolled_back == [True]
    asyncio.run(scenario())
