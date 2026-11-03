"""CI 전용 브로커에서 실제 AMQP 전달·격리·재시작 복구를 필수 검증한다."""
import os
import re
import subprocess
import time
from queue import Queue
from uuid import uuid4

import pytest
from protocol.amqp import Broker, BrokerSettings, routing_key
from gateway.progress import Listener, ProgressHub
from backend.infrastructure.progress_store import ProgressStore
from backend.infrastructure.progress_publisher import ProgressPublisher


requires_broker = pytest.mark.skipif(os.environ.get('CI_RABBITMQ') != '1', reason='실제 RabbitMQ 검증은 전용 CI 브로커에서 수행합니다.')
# 운영 설정은 읽지 않고 workflow가 생성한 테스트 전용 계정만 사용한다.
SETTINGS = BrokerSettings('127.0.0.1', 5672, '/', 'ci-magi', 'ci-only-rabbit')


def eventually(check, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.1)
    pytest.fail('CI RabbitMQ 상태 전환 시간 초과')


def queue_exists(name):
    import pika
    connection = pika.BlockingConnection(SETTINGS.parameters())
    try:
        connection.channel().queue_declare(queue=name, passive=True)
        return True
    except pika.exceptions.ChannelClosedByBroker as exc:
        if exc.reply_code == 404:
            return False
        # 다른 연결이 소유한 exclusive 큐는 존재해도 passive 조회가 거부된다.
        if exc.reply_code == 405:
            return True
        raise
    finally:
        connection.close()


@pytest.mark.parametrize(('code', 'expected'), [(404, False), (405, True), (403, None)])
def test_queue_exists_handles_exclusive_queue(monkeypatch, code, expected):
    import pika
    from unittest.mock import Mock
    connection = Mock()
    connection.channel.return_value.queue_declare.side_effect = pika.exceptions.ChannelClosedByBroker(code, 'test')
    monkeypatch.setattr(pika, 'BlockingConnection', lambda _: connection)
    if expected is None:
        with pytest.raises(pika.exceptions.ChannelClosedByBroker):
            queue_exists('test-queue')
    else:
        assert queue_exists('test-queue') is expected
    connection.channel.return_value.queue_declare.assert_called_once_with(queue='test-queue', passive=True)
    connection.close.assert_called_once_with()


@requires_broker
def test_live_broker_confirms_routing_and_unsubscribe():
    broker = Broker(SETTINGS)
    messages = Queue()
    try:
        assert broker.ready.wait(15), 'CI RabbitMQ 준비 실패: 이 검사는 skip하지 않습니다.'
        key = routing_key('test', uuid4().hex)
        subscription = broker.subscribe(key, messages.put_nowait).result(timeout=10)
        broker.publish(key, {'event': 'test', 'value': 1}).result(timeout=10)
        assert messages.get(timeout=5) == {'event': 'test', 'value': 1}
        broker.unsubscribe(subscription).result(timeout=10)
        eventually(lambda: not queue_exists(subscription[0]))
        assert broker.publish(key, {'event': 'no_subscriber'}).result(timeout=10)
    finally:
        broker.close()


@requires_broker
def test_real_user_job_queues_share_devices_and_isolate_other_jobs():
    hub = ProgressHub(SETTINGS)
    a1, a2, other, b = [Listener(None, owner) for owner in ('A', 'A', 'A', 'B')]
    ident, other_id = uuid4().hex, uuid4().hex
    try:
        assert hub.broker.ready.wait(15)
        for listener, job_id in ((a1, ident), (a2, ident), (other, other_id), (b, ident)):
            hub.attach(listener, job_id)
        assert len(hub.subscriptions) == 3
        key = routing_key('A', ident)
        token = hub.subscriptions[key].token.result(timeout=5)
        event = {'event': 'job.progress', 'job_id': ident, 'revision': 1, 'job': {'id': ident, 'status': 'running'}}
        hub.broker.publish(key, event).result(timeout=10)
        assert a1.messages.get(timeout=5) == event
        assert a2.messages.get(timeout=5) == event
        assert other.messages.empty() and b.messages.empty()
        hub.detach(a1)
        assert queue_exists(token[0])
        hub.detach(a2)
        eventually(lambda: not queue_exists(token[0]))
    finally:
        hub.close()


@requires_broker
def test_broker_restart_recovers_subscription_snapshot_and_outbox(store):
    container = os.environ.get('CI_RABBITMQ_CONTAINER', '')
    assert re.fullmatch(r'[a-f0-9]{12,64}', container), 'CI 전용 RabbitMQ container ID가 필요합니다.'
    def docker(operation):
        # 운영 스택은 조작하지 않고 workflow의 임시 서비스 컨테이너만 재시작한다.
        result = subprocess.run(['docker', operation, container], capture_output=True, timeout=60)
        assert result.returncode == 0, 'CI RabbitMQ 컨테이너 제어 실패'
    ident, owner = uuid4().hex, 'ci-outbox-owner'
    with store.transaction() as conn:
        conn.execute('INSERT INTO users(id,subject_hash) VALUES (%s,%s)', (owner, uuid4().hex))
    project = store.create_project('outbox 복구')
    publisher, hub = ProgressPublisher(store, SETTINGS), ProgressHub(SETTINGS)
    listener = Listener(None, owner)
    progress = ProgressStore(store)
    try:
        assert publisher.broker.ready.wait(15) and hub.broker.ready.wait(15)
        hub.attach(listener, ident)
        docker('stop')
        eventually(lambda: not publisher.broker.ready.is_set() and listener.failed.is_set())
        job = {'id': ident, 'project_id': project['id'], 'owner_id': owner, 'status': 'running', 'execution_id': uuid4().hex}
        store.save_job(job)
        assert progress.pending()
        docker('start')
        eventually(lambda: publisher.broker.ready.is_set() and hub.broker.ready.is_set())
        replacement = Listener(None, owner)
        hub.attach(replacement, ident)
        snapshot = progress.snapshot(ident)
        assert snapshot['job']['status'] == 'running'
        eventually(lambda: not progress.pending())
        while not replacement.messages.empty():
            replacement.messages.get_nowait()
        store.save_job({**job, 'updated_at': '2026-11-03T00:00:00Z'})
        publisher.wake.set()
        deadline = time.monotonic() + 15
        while True:
            received = replacement.messages.get(timeout=max(.1, deadline - time.monotonic()))
            if received['revision'] > snapshot['revision']:
                break
            assert time.monotonic() < deadline, '복구 후 최신 이벤트를 받지 못했습니다.'
        assert received['job_id'] == ident
        assert received['revision'] > snapshot['revision']
        eventually(lambda: not progress.pending())
    finally:
        try:
            docker('start')
        finally:
            hub.close()
            publisher.close()
