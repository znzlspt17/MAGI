"""진행 projection·outbox·사용자/작업별 구독 경계를 검증한다."""
from concurrent.futures import Future
import pytest
from backend.infrastructure.progress_store import ProgressStore, projection
from gateway.progress import Listener, ProgressHub
from protocol.amqp import routing_key


def job(store):
    project = store.create_project('실행 모니터')
    value = {'id': 'a' * 32, 'project_id': project['id'], 'status': 'queued', 'execution_id': 'e' * 32,
             'request': '요청', 'queued_at': '2026-11-03T00:00:00Z'}
    store.save_job(value)
    return value


def test_progress_allowlist_excludes_provider_output():
    result = projection({'id': 'j', 'status': 'running', 'provider_response': 'DO_NOT_COPY'},
                        [{'id': 's', 'stage': 'planner', 'result': {'raw_response': 'DO_NOT_COPY'}}])
    assert 'DO_NOT_COPY' not in str(result)


def test_outbox_and_state_rollback_together(store):
    value = job(store)
    progress = ProgressStore(store)
    first = progress.snapshot(value['id'])
    before = len(progress.pending())
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.save_job({**value, 'status': 'running'})
            raise RuntimeError('rollback')
    assert progress.snapshot(value['id'])['revision'] == first['revision']
    assert progress.snapshot(value['id'])['job']['status'] == 'queued'
    assert len(progress.pending()) == before


def test_revision_changes_only_for_observable_state(store):
    value = job(store)
    progress = ProgressStore(store)
    first = progress.snapshot(value['id'])
    store.save_job({**value, 'untrusted_diagnostic': 'DO_NOT_COPY'})
    assert progress.snapshot(value['id'])['revision'] == first['revision']
    store.save_job({**value, 'status': 'running'})
    assert progress.snapshot(value['id'])['revision'] == first['revision'] + 1
    assert 'DO_NOT_COPY' not in str(progress.pending())
    with store.transaction() as conn:
        conn.execute('DELETE FROM jobs WHERE id=%s', (value['id'],))
    assert not progress.pending()


class FakeBroker:
    def __init__(self, url, on_disconnect):
        self.subscriptions, self.removed = [], []
    def subscribe(self, key, receive):
        future = Future()
        token = (key, len(self.subscriptions))
        self.subscriptions.append((key, receive))
        future.set_result(token)
        return future
    def unsubscribe(self, token):
        self.removed.append(token)
    def close(self):
        pass


def test_each_user_job_has_one_queue_and_multiple_devices_share_it():
    hub = ProgressHub('fake', FakeBroker)
    a1, a2, other_job, b = [Listener(None, owner) for owner in ('A', 'A', 'A', 'B')]
    try:
        for listener, ident in ((a1, 'a' * 32), (a2, 'a' * 32), (other_job, 'b' * 32), (b, 'c' * 32)):
            hub.attach(listener, ident)
        assert len(hub.broker.subscriptions) == 3
        hub.deliver(routing_key('A', 'a' * 32), {'event': 'job.progress', 'job_id': 'a'*32, 'revision': 1, 'job': {'id': 'a'*32, 'status': 'running'}})
        assert a1.messages.get(timeout=2)['event'] == 'job.progress'
        assert a2.messages.get(timeout=2)['event'] == 'job.progress'
        assert other_job.messages.empty() and b.messages.empty()
        hub.detach(a1)
        assert not hub.broker.removed
        hub.detach(a2)
        assert len(hub.broker.removed) == 1
    finally:
        hub.close()


def test_slow_connection_is_bounded_and_does_not_block_other_devices():
    listener = Listener(None, 'A')
    for _ in range(65):
        listener.put({'event': 'job.progress'})
    assert listener.failed.is_set()
    assert listener.messages.qsize() == 64


def test_expired_session_is_reported_before_socket_close():
    from gateway.progress import serve_progress
    from gateway.client import ClientError
    class Client:
        checks = 0
        def call(self, method, params=None):
            if method == 'progress.authorize':
                self.checks += 1
                if self.checks > 1:
                    raise ClientError('세션 만료', status=401)
                return {'id': 'A'}
            return {'jobs': [], 'revisions': {}}
    class Hub:
        detached = False
        def attach(self, listener):
            listener.put({'event': 'jobs.changed', 'job_id': 'a'*32})
        def detach(self, listener):
            self.detached = True
    class Socket:
        sent = []
        def send(self, text):
            import json
            self.sent.append(json.loads(text)['event'])
        def receive(self, timeout):
            return None
        def close(self):
            self.sent.append('closed')
    socket, hub = Socket(), Hub()
    serve_progress(socket, Client(), hub)
    assert socket.sent[-2:] == ['session.expired', 'closed']
    assert hub.detached


def test_progress_authorization_checks_owner_without_consuming_user_request_quota():
    from types import SimpleNamespace
    from backend.access.service import PublicService
    from backend.access.context import ACTOR
    def get(ident):
        assert ACTOR.get()['id'] == 'A'
        if ident != 'a'*32:
            raise KeyError(ident)
    service = object.__new__(PublicService)
    service.manager = SimpleNamespace(get=get)
    service.access = SimpleNamespace(session=lambda sid: {'id': 'A'})
    packet = {'method': 'progress.authorize', 'params': {'id': 'a'*32}, 'session': 'fake-session'}
    assert service.invoke(packet, None) == {'id': 'A'}
    with pytest.raises(KeyError):
        service.invoke({**packet, 'params': {'id': 'b'*32}}, None)
    assert ACTOR.get() is None


@pytest.mark.parametrize('owner,ident', [('A.*', 'a'*32), ('A', '#'), ('', 'a'*32)])
def test_routing_keys_cannot_inject_wildcards(owner, ident):
    with pytest.raises(ValueError):
        routing_key(owner, ident)
