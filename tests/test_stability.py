"""실행 시작·정리 실패와 민감정보 없는 오류 기록을 검증한다."""

import asyncio
from concurrent.futures import Future
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import Mock, call

import pytest

from backend.access.context import ACTOR, METER, TRANSACTION
from backend.access.recovery import Execution, Failure, WorkerRecovery
from backend.access.service import PublicService
from backend.knowledge.config import KnowledgeError
from backend.knowledge.runtime import KnowledgeService
from backend.server.app import MagiServer
from gateway.app import create_app
from test_public_service import account, store


@pytest.fixture
def admitted(store, tmp_path, monkeypatch):
    monkeypatch.setenv('MAGI_SPEC_OPENAI_MODEL', 'gpt-6-luna')
    prices = {'gpt-6-luna': {'input_usd_per_million': '1', 'output_usd_per_million': '2',
                           'context_tokens': 1000, 'max_output_tokens': 100, 'context_limit_verified': True}}
    async def create():
        return MagiServer(tmp_path, knowledge=KnowledgeService(store),
                          public=lambda manager: PublicService(manager, prices=prices, pepper='fake-test'))
    server = asyncio.run(create())
    future = Future()
    monkeypatch.setattr(server.manager.executor, 'submit', Mock(return_value=future))
    sid, actor = account(server.public.access, 'test-owner')
    request = {'request_id': 'test', 'method': 'generate', 'params': {'request': 'A test app'},
               'session': sid, 'csrf': actor['csrf'], 'idempotency_key': 'test-admission'}
    import json
    result = json.loads(server._dispatch(request))
    assert 'result' in result, result
    ident = result['result']['id']
    execution = Execution.from_job(server.manager.jobs[ident])
    try:
        yield server, execution, actor, future
    finally:
        server.manager.close()


@pytest.mark.parametrize('failure_at', ['job', 'owner'])
def test_lookup_failure_is_atomic_and_does_not_refund_run(admitted, monkeypatch, failure_at):
    server, execution, actor, future = admitted
    service = server.public
    engine = Mock()
    monkeypatch.setattr(server.manager, '_run', engine)
    monkeypatch.setattr(service.access, 'session_for_worker', Mock(side_effect=KnowledgeError('fake-sensitive-detail')))
    if failure_at == 'job':
        server.manager.jobs.pop(execution.ident)
    actor_token = ACTOR.set({'id': 'outer-actor'})
    meter_token = METER.set(object())
    previous_meter = METER.get()
    try:
        with pytest.raises((KnowledgeError, KeyError)):
            service.worker(execution.ident, 'generate', None, execution=execution)
        assert ACTOR.get() == {'id': 'outer-actor'} and METER.get() is previous_meter
    finally:
        ACTOR.reset(actor_token)
        METER.reset(meter_token)
    engine.assert_not_called()
    assert server.manager.get(execution.ident)['status'] == 'error'
    assert service.store.action_records(execution.ident)[0]['status'] == 'error'
    assert not service.access.status(actor['id'])['busy']
    assert service.access.usage(actor['id'])['runs'] == 1
    with service.store.transaction(mode='read') as c:
        call = c.execute('SELECT state,actual FROM magi_cost_calls WHERE id=%s', (execution.initial[0],)).fetchone()
        usage = c.execute('SELECT reserved FROM magi_daily_usage WHERE user_id=%s', (actor['id'],)).fetchone()
    assert call['state'] == 'settled' and Decimal(str(call['actual'])) == 0
    assert Decimal(str(usage['reserved'])) == 0
    service.recovery.record(Failure(execution, False, execution.initial))
    assert not service.recovery.pending


def test_failed_cleanup_retries_only_cleanup_and_ignores_later_generation(admitted, monkeypatch):
    server, execution, actor, future = admitted
    service = server.public
    original = service.store.transaction
    @contextmanager
    def offline(**kwargs):
        raise KnowledgeError('fake DB unavailable')
        yield
    monkeypatch.setattr(service.store, 'transaction', offline)
    engine = Mock()
    monkeypatch.setattr(server.manager, '_run', engine)
    with pytest.raises(KnowledgeError):
        service.worker(execution.ident, 'generate', None, execution=execution)
    assert execution in service.recovery.pending
    assert server.manager.jobs[execution.ident]['status'] == 'queued'
    monkeypatch.setattr(service.store, 'transaction', original)
    settle = service.access.settle
    def interrupted_settle(*args):
        settle(*args)
        raise KnowledgeError('fake cleanup interruption')
    monkeypatch.setattr(service.access, 'settle', interrupted_settle)
    service.recovery.retry()
    assert execution in service.recovery.pending
    with service.store.transaction(mode='read') as c:
        assert c.execute('SELECT data FROM magi_jobs WHERE id=%s', (execution.ident,)).fetchone()['data']['status'] == 'queued'
        assert c.execute('SELECT state FROM magi_cost_calls WHERE id=%s', (execution.initial[0],)).fetchone()['state'] == 'reserved'
    monkeypatch.setattr(service.access, 'settle', settle)
    service.recovery.retry()
    assert not service.recovery.pending and not service.access.status(actor['id'])['busy']
    engine.assert_not_called()
    with service.store.transaction() as c:
        generation = service.access.acquire(c, actor['id'], execution.ident)
    server.manager.jobs[execution.ident].update(lease_generation=generation, execution_id='new-execution', status='queued')
    service.recovery.record(Failure(execution, False, execution.initial))
    assert service.access.status(actor['id'])['busy']
    assert server.manager.jobs[execution.ident]['execution_id'] == 'new-execution'


def test_initialization_and_uncertain_engine_failure_restore_context(admitted, monkeypatch):
    server, execution, actor, future = admitted
    service = server.public
    original_meter = __import__('backend.access.service', fromlist=['Meter']).Meter
    monkeypatch.setattr('backend.access.service.Meter', Mock(side_effect=RuntimeError('fake-init-failure')))
    with pytest.raises(RuntimeError):
        service.worker(execution.ident, 'generate', None, execution=execution)
    assert ACTOR.get() is None and METER.get() is None
    monkeypatch.setattr('backend.access.service.Meter', original_meter)
    # 외부 호출이 시작된 뒤의 실패는 미확정 비용을 보존한다.
    with service.store.transaction() as c:
        generation = service.access.acquire(c, actor['id'], execution.ident)
    initial = service.access.reserve(actor['id'], execution.ident, generation, 'gpt-6-luna', Decimal('.0012'))
    job = server.manager.jobs[execution.ident]
    job.update(lease_generation=generation, status='queued', _initial_reservation=(initial, 'gpt-6-luna'))
    service.store.save_job(job)
    def uncertain(*args):
        meter = METER.get()
        reservation = meter.reserve('gpt-6-luna')
        meter.settle(reservation, 'gpt-6-luna', None)
        raise RuntimeError('fake-provider-failure')
    monkeypatch.setattr(server.manager, '_run', uncertain)
    with pytest.raises(RuntimeError):
        service.worker(execution.ident, 'generate', None)
    assert ACTOR.get() is None and METER.get() is None
    assert service.access.status(actor['id'])['recovering']
    with service.store.transaction(mode='read') as c:
        assert c.execute('SELECT state FROM magi_cost_calls WHERE id=%s', (initial,)).fetchone()['state'] == 'uncertain'


def test_submit_failure_and_future_errors_are_observed(admitted, monkeypatch, caplog):
    server, execution, actor, future = admitted
    future.set_exception(RuntimeError('fake-sensitive-future'))
    assert not server.manager._futures
    assert 'worker failed' in caplog.text and 'fake-sensitive-future' not in caplog.text
    monkeypatch.setattr(server.manager.executor, 'submit', Mock(side_effect=RuntimeError('fake-submit-failure')))
    with pytest.raises(RuntimeError):
        server.manager._submit_locked(execution.ident, 'generate', None)
    assert not server.public.access.status(actor['id'])['busy']
    assert server.manager.jobs[execution.ident]['status'] == 'error'


@pytest.mark.parametrize('new_lease', [False, True])
def test_commit_response_loss_is_reconciled_without_rerunning(admitted, monkeypatch, new_lease):
    server, execution, actor, future = admitted
    service = server.public
    original = service.store.transaction
    @contextmanager
    def lost_response(**kwargs):
        outermost = TRANSACTION.get() is None
        with original(**kwargs) as c:
            yield c
        if outermost:
            raise KnowledgeError('fake commit response loss')
    monkeypatch.setattr(service.store, 'transaction', lost_response)
    service.recovery.record(Failure(execution, False, execution.initial))
    assert execution in service.recovery.pending
    assert server.manager.jobs[execution.ident]['status'] == 'queued'
    monkeypatch.setattr(service.store, 'transaction', original)
    if new_lease:
        with service.store.transaction() as c:
            service.access.acquire(c, actor['id'], 'another-job')
    service.recovery.retry()
    assert not service.recovery.pending
    assert server.manager.jobs[execution.ident]['status'] == 'error'
    assert service.access.status(actor['id'])['busy'] is new_lease


def test_recovery_loop_waits_five_seconds_and_never_runs_engine():
    service = Mock()
    recovery = WorkerRecovery(service)
    recovery.retry = Mock()
    recovery.stopped.wait = Mock(side_effect=[False, True])
    recovery._loop()
    assert recovery.stopped.wait.call_args_list == [call(5), call(5)]
    recovery.retry.assert_called_once_with()
    service.manager._run.assert_not_called()


def test_gateway_unexpected_error_has_one_safe_correlated_log(caplog):
    class Client:
        def __init__(self, url):
            pass
        def call(self, *args):
            raise RuntimeError('fake-sensitive-detail')
    app = create_app({'TESTING': True, 'MAGI_PUBLIC_MODE': False, 'MAGI_CLIENT_FACTORY': Client})
    with app.test_client() as browser:
        response = browser.get('/api/no-such-route?secret=fake-query', headers={'Authorization': 'fake-header'})
    assert response.status_code == 404
    with app.test_client() as browser:
        response = browser.get('/api/jobs?secret=fake-query', headers={'Authorization': 'fake-header'})
    records = [r for r in caplog.records if 'unexpected request failure' in r.getMessage()]
    assert response.status_code == 500 and len(records) == 1
    assert response.headers['X-Request-ID'] == response.json['request_id']
    assert response.json['request_id'] in records[0].getMessage()
    assert 'route=/api/jobs' in records[0].getMessage() and 'RuntimeError' in records[0].getMessage()
    assert 'lineno' in records[0].getMessage() and not records[0].exc_info
    for value in ('fake-sensitive-detail', 'fake-query', 'fake-header'):
        assert value not in caplog.text and value not in response.text
