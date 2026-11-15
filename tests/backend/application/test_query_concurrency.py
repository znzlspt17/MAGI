import asyncio
from types import SimpleNamespace

import pytest

from backend.application.activity import tracked
from backend.application.document_queries import DocumentQueries
from backend.application.impact_queries import ImpactQueries
from backend.application.requirement_queries import RequirementQueries


@pytest.mark.parametrize('kind', ['step', 'package', 'requirements', 'impact', 'activity'])
def test_slow_job_lookup_does_not_hold_global_manager_lock(kind):
    async def scenario():
        lock = asyncio.Lock()
        entered = asyncio.Event()
        release = asyncio.Event()

        class Access:
            knowledge = None
            async def get(self, ident):
                entered.set()
                await release.wait()
                raise KeyError(ident)
            async def documents(self, ident): raise AssertionError()
            async def engine(self, ident, meter=None): raise AssertionError()
            async def state(self, ident): raise AssertionError()
            async def read_json(self, *args): raise AssertionError()
            async def read_text(self, *args): raise AssertionError()

        access = Access()
        docs = DocumentQueries(access, lock=lock, activities={}, document_locks={})
        requirements = RequirementQueries(access, lock=lock, documents=docs)
        impact = ImpactQueries(access, lock=lock, activities={}, document_locks={})

        class Activity:
            _activities = {}
            get = access.get
            @tracked
            async def work(self, ident): pass

        activity = Activity()
        activity.lock = lock
        operations = {
            'step': lambda: docs.step('job', 'step'),
            'package': lambda: docs.implementation_package('job', {}),
            'requirements': lambda: requirements.requirement_review('job', {}),
            'impact': lambda: impact.impact_context({'job_id': 'job'}),
            'activity': lambda: activity.work('job'),
        }
        task = asyncio.create_task(operations[kind]())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            async with asyncio.timeout(.1):
                async with lock:
                    pass
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
