import asyncio
from contextlib import asynccontextmanager
import pytest

from backend.access.store import AccessStore
from backend.access.billing import Meter
from backend.access.service import PublicService
from backend.mcp_client.service import MCPService
from backend.access.runtime import PublicRuntime


def test_guest_creation_awaits_database_and_allows_other_tasks():
    class Connection:
        def __init__(self):
            self.statements = []
            self.started = asyncio.Event()
            self.proceed = asyncio.Event()

        async def execute(self, sql, params):
            self.statements.append(sql)
            self.started.set()
            await self.proceed.wait()

    class Store:
        def __init__(self): self.conn = Connection()
        @asynccontextmanager
        async def transaction(self, mode='write'):
            yield self.conn

    async def scenario():
        store = Store()
        task = asyncio.create_task(AccessStore(store).guest())
        await asyncio.wait_for(store.conn.started.wait(), 1)
        assert not task.done()
        store.conn.proceed.set()
        assert isinstance(await task, str)
        assert len(store.conn.statements) == 2

    asyncio.run(scenario())


def test_meter_awaits_execution_and_reservation_before_marking_called():
    class Access:
        def __init__(self): self.calls = []
        async def check_execution(self, *args): self.calls.append('check')
        async def reserve(self, *args, **kwargs): self.calls.append('reserve'); return 'call'
        async def mark_called(self, *args, **kwargs): self.calls.append('called')
    async def scenario():
        access = Access()
        meter = Meter(access, 'owner', 'job', 1, {}, execution_id='run')
        assert await meter.reserve('unpriced') == 'call'
        assert access.calls == ['check', 'reserve', 'called']
    asyncio.run(scenario())


def test_guest_rpc_awaits_identity_store_without_google():
    class Access:
        async def guest(self, sid): return 'guest-session'
        async def session(self, sid): return {'expires_at': 1000}
        def clock(self): return 0
    async def scenario():
        service = object.__new__(PublicService)
        service.access = Access()
        service.google = None
        service.pepper = ''
        result = await service.invoke({'method': 'auth.guest', 'params': {}}, None)
        assert result == {'session': 'guest-session', 'max_age': 1000}
    asyncio.run(scenario())


def test_me_includes_authorized_owners_for_draft_recovery():
    class Access:
        async def session(self, sid):
            return {'id': 'account', 'owner_ids': ['account', 'guest'], 'role': 'user',
                    'expires_at': 1000, 'csrf': 'csrf', 'identity_kind': 'google'}
        async def throttle(self, ident): pass
    async def scenario():
        service = object.__new__(PublicService)
        service.access = Access()
        response = await service.invoke({'method': 'auth.me', 'params': {}, 'session': 'sid'}, None)
        assert response['owner_ids'] == ['account', 'guest']
    asyncio.run(scenario())


def test_linked_account_lists_guest_mcp_connections():
    class Cursor:
        async def fetchall(self):
            return [{'id': 'one', 'name': 'guest-mcp', 'url': 'https://example.test',
                     'auth_type': 'none', 'enabled': False, 'status': 'disconnected',
                     'secret_ciphertext': None, 'oauth_client_id': None,
                     'api_key_header': None, 'tools': []}]
    class Connection:
        async def execute(self, sql, params):
            assert set(params[0]) == {'account', 'guest'}
            return Cursor()
    class Store:
        @asynccontextmanager
        async def transaction(self, mode='write'): yield Connection()
    async def scenario():
        rows = await MCPService(Store()).list('account', ['account', 'guest'])
        assert rows['connections'][0]['id'] == 'one'
    asyncio.run(scenario())


def test_process_lock_uses_a_dedicated_async_connection(monkeypatch):
    from types import SimpleNamespace
    import psycopg
    class Cursor:
        def __init__(self, row): self.row = row
        async def fetchone(self): return self.row
    class Connection:
        closed = False
        async def execute(self, sql, params=()):
            return Cursor({'rolsuper': False, 'rolbypassrls': False} if 'pg_roles' in sql else {'acquired': True})
        async def commit(self): pass
        async def close(self): self.closed = True
    connection = Connection()
    async def connect(**kwargs): return connection
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
    async def scenario():
        store = SimpleNamespace(config=SimpleNamespace(connection={}), connect=lambda **kwargs: connection)
        runtime = PublicRuntime(store)
        await runtime.acquire(recover=False)
        assert runtime.connection is connection
        await runtime.close()
        assert connection.closed
    asyncio.run(scenario())


def test_cancelled_process_lock_initialization_closes_dedicated_connection(monkeypatch):
    from types import SimpleNamespace
    import psycopg
    async def scenario():
        started = asyncio.Event()
        class Connection:
            closed = False
            async def execute(self, sql, params=()):
                started.set()
                await asyncio.Event().wait()
            async def close(self): self.closed = True
        connection = Connection()
        async def connect(**kwargs): return connection
        monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
        runtime = PublicRuntime(SimpleNamespace(config=SimpleNamespace(connection={})))
        task = asyncio.create_task(runtime.acquire(recover=False))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert connection.closed and runtime.connection is None
    asyncio.run(scenario())


def test_cancelled_worker_schedules_execution_recovery():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.access.capacity import ExecutionCapacity
    from backend.access.recovery import Execution
    started = None
    async def scenario():
        nonlocal started
        started = asyncio.Event()
        async def run(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        job = {'owner_id': 'owner', 'execution_id': 'run', 'execution_generation': 1}
        manager = SimpleNamespace(lock=asyncio.Lock(), jobs={'job': job}, _run=run)
        access = SimpleNamespace(session_for_worker=AsyncMock(return_value={'id': 'owner'}), start=AsyncMock())
        service = object.__new__(PublicService)
        service.manager, service.access = manager, access
        service.capacity, service.recovery, service.prices = ExecutionCapacity(), SimpleNamespace(record=AsyncMock()), {}
        task = asyncio.create_task(service.worker('job', 'generate', {}, execution=Execution('job', 'run', 1, None)))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        service.recovery.record.assert_awaited_once()
        assert service.capacity.active == 0
    import pytest
    asyncio.run(scenario())


@pytest.mark.parametrize('existing', [False, True])
def test_cancelled_admission_restores_memory_and_rolls_back(existing):
    from copy import deepcopy
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from backend.access.context import ADMISSION

    async def scenario():
        entered, pending = asyncio.Event(), asyncio.Event()
        old = {'id': 'job', 'owner_id': 'owner', 'execution_id': 'old', 'status': 'waiting'}
        jobs = {'job': deepcopy(old)} if existing else {}
        class Store:
            rolled_back = False
            @asynccontextmanager
            async def transaction(self, mode='write'):
                try:
                    yield object()
                except BaseException:
                    self.rolled_back = True
                    raise
            async def _save_job(self, conn, job):
                entered.set()
                await pending.wait()
        store = Store()
        manager = SimpleNamespace(jobs=jobs, job_lock=lambda jid: asyncio.Lock(),
                                  get=AsyncMock(return_value=old), _submit_locked=Mock())
        access = SimpleNamespace(acquire=AsyncMock(return_value=1), check_money=AsyncMock(),
                                 reserve=AsyncMock(return_value='call'), clock=lambda: 1800000000)
        service = object.__new__(PublicService)
        service.manager, service.store, service.access = manager, store, access
        service.capacity = SimpleNamespace(check_admission=AsyncMock())
        service.previous_admission, service.prices = AsyncMock(return_value=None), {}
        async def dispatch(request):
            jid, execution_id = ADMISSION.get()
            jobs[jid] = {'id': jid, 'owner_id': 'owner', 'execution_id': execution_id, 'status': 'queued'}
            return {'id': jid}
        request = {'method': 'answer' if existing else 'generate', 'idempotency_key': 'operation-1',
                   'params': {'id': 'job', 'execution_id': 'old'} if existing else {}}
        task = asyncio.create_task(service.admit({'id': 'owner', 'owner_ids': ['owner']}, request, dispatch))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.rolled_back
        assert jobs == ({'job': old} if existing else {})
        manager._submit_locked.assert_not_called()
    asyncio.run(scenario())


def test_admin_overview_does_not_hold_manager_lock_while_waiting_for_db():
    from types import SimpleNamespace
    async def scenario():
        writer = asyncio.Lock()
        got_writer, admin_waiting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Cursor:
            async def fetchall(self): return []
            async def fetchone(self): return {'daily_usd': 10}
        class Connection:
            async def execute(self, sql, params=()): return Cursor()
        class Store:
            @asynccontextmanager
            async def transaction(self, mode='write'):
                admin_waiting.set()
                async with writer:
                    yield Connection()
        manager = SimpleNamespace(lock=asyncio.Lock(), knowledge=SimpleNamespace(last_error=None), jobs={})
        service = object.__new__(PublicService)
        service.manager, service.store = manager, Store()
        async def user_action():
            async with writer:
                got_writer.set()
                await release.wait()
                async with manager.lock:
                    return 'completed'
        action = asyncio.create_task(user_action())
        await asyncio.wait_for(got_writer.wait(), 1)
        admin = asyncio.create_task(service.admin({'id': 'admin', 'role': 'admin'}, 'admin.overview', {}))
        await asyncio.wait_for(admin_waiting.wait(), 1)
        release.set()
        assert (await asyncio.wait_for(asyncio.gather(action, admin), 1))[0] == 'completed'
    asyncio.run(scenario())


def test_submission_failure_repairs_committed_execution_after_job_lock_release():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from backend.access.context import ADMISSION, DEFERRED, AccessError

    async def scenario():
        lock = asyncio.Lock()
        jobs = {}
        class Store:
            @asynccontextmanager
            async def transaction(self, mode='write'):
                yield SimpleNamespace(execute=AsyncMock())
            async def _save_job(self, conn, job):
                pass
            def _json(self, result):
                return result
        manager = SimpleNamespace(jobs=jobs, job_lock=lambda jid: lock,
                                  _submit_locked=Mock(side_effect=RuntimeError('no task')))
        access = SimpleNamespace(acquire=AsyncMock(return_value=1), check_money=AsyncMock(),
                                 reserve=AsyncMock(return_value='call'), clock=lambda: 1800000000)
        service = object.__new__(PublicService)
        service.manager, service.store, service.access = manager, Store(), access
        service.capacity = SimpleNamespace(check_admission=AsyncMock())
        service.previous_admission, service.prices = AsyncMock(return_value=None), {}
        async def repair(failure):
            assert not lock.locked()
            assert failure.execution.ident in jobs
        service.recovery = SimpleNamespace(record=AsyncMock(side_effect=repair))
        async def dispatch(request):
            jid, execution_id = ADMISSION.get()
            jobs[jid] = {'id': jid, 'owner_id': 'owner', 'execution_id': execution_id, 'status': 'queued'}
            DEFERRED.get().append((jid, 'generate', {}))
            return {'id': jid}
        with pytest.raises(AccessError) as error:
            await asyncio.wait_for(service.admit({'id': 'owner', 'owner_ids': ['owner']},
                {'method': 'generate', 'idempotency_key': 'operation-1', 'params': {}}, dispatch), 1)
        assert error.value.code == 'unavailable'
        service.recovery.record.assert_awaited_once()
    asyncio.run(scenario())
