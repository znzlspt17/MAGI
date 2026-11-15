"""독립 SQL DB와 가짜 모델로 사용자 100명의 실제 작업 경로를 함께 실행한다."""

import asyncio
from types import SimpleNamespace

from backend.access.context import ACTOR
from backend.access.store import AccessStore
from backend.server.job_manager import JobManager
from tests.backend.application.async_helpers import run_async


@run_async
async def test_native_workflow_supports_one_hundred_users_with_bounded_model_slots(async_store_factory):
    async with async_store_factory() as store:
        access = AccessStore(store)
        release = asyncio.Event()
        hundred_started = asyncio.Event()
        entered = 0
        active = 0
        peak = 0

        class FakeEngine:
            def __init__(self, documents, runtime):
                self.documents = documents

            async def execute(self, action, payload, *, on_progress=None):
                nonlocal entered, active, peak
                entered += 1
                active += 1
                peak = max(peak, active)
                if entered == 100:
                    hundred_started.set()
                try:
                    await release.wait()
                    return SimpleNamespace(status="NEEDS_USER_INPUT", wait_reason="")
                finally:
                    active -= 1

        async def close():
            pass

        knowledge = SimpleNamespace(store=store, close=close)
        manager = await JobManager.build(knowledge, engine_factory=FakeEngine)
        try:
            owners = set()
            for index in range(101):
                actor = await access.session(await access.guest())
                owners.add(actor["id"])
                token = ACTOR.set(actor)
                try:
                    await manager.create(f"동시 작업 {index}")
                finally:
                    ACTOR.reset(token)
            await asyncio.wait_for(hundred_started.wait(), timeout=15)
            assert len(owners) == 101
            assert entered == 100
            assert active == peak == 100
            tasks = list(manager._futures)
            assert len(tasks) == 101
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
            assert entered == 101 and active == 0 and peak == 100
            assert all(job["status"] == "NEEDS_USER_INPUT" for job in manager.jobs.values())
        finally:
            release.set()
            await manager.close()
