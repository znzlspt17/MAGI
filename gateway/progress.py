"""단일 게이트웨이의 사용자·작업별 AMQP 구독과 WebSocket 분배."""
from dataclasses import dataclass, field
from queue import Queue, Empty, Full
import threading
import time
from datetime import UTC, datetime

from protocol.amqp import Broker, routing_key
from gateway.client import ClientError


@dataclass(eq=False)
class Listener:
    client: object
    owner: str
    messages: Queue = field(default_factory=lambda: Queue(maxsize=64))
    failed: threading.Event = field(default_factory=threading.Event)
    keys: set = field(default_factory=set)

    def put(self, event):
        try:
            self.messages.put_nowait(event)
        except Full:
            self.failed.set()


@dataclass
class Subscription:
    listeners: set = field(default_factory=set)
    token: object = None


class ProgressHub:
    def __init__(self, settings, broker_factory=Broker):
        self.lock = threading.RLock()
        self.subscriptions = {}
        self.events: Queue[tuple[str, dict]] = Queue(maxsize=2048)
        self.stopped = threading.Event()
        self.broker = broker_factory(settings, on_disconnect=self.disconnected)
        self.thread = threading.Thread(target=self._dispatch, name='progress-relay', daemon=True)
        self.thread.start()

    def _dispatch(self):
        while not self.stopped.is_set():
            try:
                key, event = self.events.get(timeout=1)
            except Empty:
                continue
            with self.lock:
                entry = self.subscriptions.get(key)
                listeners = tuple(entry.listeners) if entry else ()
            if event.get('event') == 'job.progress' and event.get('job', {}).get('status') not in {'queued', 'running'}:
                for listener in listeners:
                    try:
                        event = listener.client.call('progress.snapshot', {'id': event['job_id']})
                        break
                    except ClientError:
                        listener.failed.set()
                else:
                    continue
            for listener in listeners:
                if not listener.failed.is_set():
                    listener.put({**event, '_route_owner': key.split('.')[1]})

    def disconnected(self):
        with self.lock:
            for entry in self.subscriptions.values():
                entry.token = None
                for listener in entry.listeners:
                    listener.failed.set()
            self.subscriptions.clear()

    def attach(self, listener, job=None, owner=None):
        key = routing_key(owner or listener.owner, job)
        with self.lock:
            entry = self.subscriptions.setdefault(key, Subscription())
            entry.listeners.add(listener)
            listener.keys.add(key)
            if entry.token is None:
                # 다른 접속도 동일한 Future를 기다려 중복 큐 생성을 방지한다.
                entry.token = self.broker.subscribe(key, lambda event: self.deliver(key, event))
            future = entry.token
        try:
            future.result(timeout=10)
        except Exception:
            self.detach(listener, key)
            raise ClientError('실시간 상태 서버에 연결할 수 없습니다.') from None

    def deliver(self, key, event):
        if not isinstance(event, dict) or event.get('event') not in {'job.progress', 'jobs.changed', 'records.deleted'}:
            raise ValueError('이벤트 형식 오류')
        kind = event['event']
        if kind in {'job.progress', 'jobs.changed'}:
            ident, revision, job = event.get('job_id'), event.get('revision'), event.get('job')
            if not isinstance(job, dict) or job.get('id') != ident or type(revision) is not int or revision < 1:
                raise ValueError('이벤트 식별값 오류')
            owner = key.split('.')[1]
            expected = routing_key(owner, ident) if kind == 'job.progress' else routing_key(owner)
            if key != expected:
                raise ValueError('이벤트 구독 경로 오류')
        elif not key.endswith('.list') or not isinstance(event.get('ids'), list):
            raise ValueError('삭제 이벤트 형식 오류')
        with self.lock:
            entry = self.subscriptions.get(key)
            if not entry:
                return
            try:
                self.events.put_nowait((key, event))
            except Full:
                for listener in entry.listeners:
                    listener.failed.set()

    def detach(self, listener, key=None):
        with self.lock:
            for target in [key] if key else tuple(listener.keys):
                listener.keys.discard(target)
                entry = self.subscriptions.get(target)
                if not entry:
                    continue
                entry.listeners.discard(listener)
                if not entry.listeners:
                    self.subscriptions.pop(target, None)
                    future = entry.token
                    def remove(done):
                        try:
                            self.broker.unsubscribe(done.result())
                        except Exception:
                            pass
                    future.add_done_callback(remove)

    def close(self):
        self.stopped.set()
        self.broker.close()
        self.thread.join(timeout=12)


def serve_progress(ws, client, hub):
    import json
    import re
    actor = client.call('progress.authorize')
    listener = Listener(client, actor['id'])
    current = None
    current_owner = None
    owners = set(actor.get('owner_ids', [actor['id']]))
    checked = time.monotonic()

    def verify_actor(current):
        # 2026-11-15: 다른 계정의 상태를 기존 클라이언트 인증 문맥에 섞지 않는다.
        if current.get('id') != listener.owner:
            raise ClientError('세션이 변경되었습니다.', status=401)
    try:
        hub.attach(listener)
        for owner in owners - {listener.owner}:
            hub.attach(listener, owner=owner)
        ws.send(json.dumps({'event': 'ready'}))
        ws.send(json.dumps({'event': 'jobs.snapshot', **client.call('progress.list')}, ensure_ascii=False))
        while not listener.failed.is_set():
            raw = ws.receive(timeout=0.1)
            if raw is not None:
                try:
                    command = json.loads(raw)
                    action, ident = command.get('event'), command.get('job_id')
                    if action not in {'job.subscribe', 'job.unsubscribe', 'job.resync'} or not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
                        raise ValueError()
                    if action == 'job.unsubscribe':
                        if current == ident:
                            hub.detach(listener, routing_key(current_owner, ident))
                            current = None
                            current_owner = None
                        continue
                    # DB 스냅샷은 RLS와 작업 소유권을 확인한 RPC에서만 얻는다.
                    authorized = client.call('progress.authorize', {'id': ident})
                    verify_actor(authorized)
                    owner = authorized.get('owner_id', listener.owner)
                    if owner not in authorized.get('owner_ids', [listener.owner]):
                        raise ValueError()
                    if action == 'job.subscribe' and current != ident:
                        if current:
                            hub.detach(listener, routing_key(current_owner, current))
                        if owner == listener.owner:
                            hub.attach(listener, ident)
                        else:
                            hub.attach(listener, ident, owner=owner)
                        current = ident
                        current_owner = owner
                    if current != ident:
                        raise ValueError()
                    snapshot = client.call('progress.snapshot', {'id': ident})
                    ws.send(json.dumps(snapshot, ensure_ascii=False))
                except ClientError as exc:
                    if exc.status == 401:
                        raise
                    ws.send(json.dumps({'event': 'job.subscription_error'}))
                except (ValueError, TypeError, AttributeError):
                    ws.send(json.dumps({'event': 'job.subscription_error'}))
            for _ in range(64):
                try:
                    event = listener.messages.get_nowait()
                except Empty:
                    break
                if _ == 0:
                    # 연결 생존 확인과 별개로 철회된 세션의 데이터 전송을 차단한다.
                    auth = client.call('progress.authorize')
                    verify_actor(auth)
                    current_owners = set(auth.get('owner_ids', [listener.owner]))
                    for owner in current_owners - owners:
                        hub.attach(listener, owner=owner)
                    for owner in owners - current_owners:
                        hub.detach(listener, routing_key(owner))
                        if current and current_owner == owner:
                            hub.detach(listener, routing_key(owner, current))
                            current = None
                            current_owner = None
                    if current_owners != owners:
                        # 2026-11-13: 연결된 기존 작업은 새 이벤트가 없으므로 범위 변경 시 목록을 다시 보낸다.
                        ws.send(json.dumps({'event': 'jobs.snapshot', **client.call('progress.list')}, ensure_ascii=False))
                    owners = current_owners
                route_owner = event.pop('_route_owner', listener.owner)
                if route_owner not in owners:
                    continue
                if event['event'] == 'job.progress':
                    if event.get('job_id') != current:
                        continue
                if event['event'] == 'job.snapshot' and event.get('job_id') != current:
                    continue
                if event['event'] == 'records.deleted':
                    for deleted in event.get('ids', []):
                        hub.detach(listener, routing_key(route_owner, deleted))
                        if current == deleted:
                            current = None
                            current_owner = None
                if event['event'] in {'job.progress', 'job.snapshot'}:
                    event = {**event, 'server_time': datetime.now(UTC).isoformat()}
                ws.send(json.dumps(event, ensure_ascii=False))
            if time.monotonic() - checked >= 30:
                auth = client.call('progress.authorize')
                verify_actor(auth)
                current_owners = set(auth.get('owner_ids', [listener.owner]))
                for owner in current_owners - owners:
                    hub.attach(listener, owner=owner)
                for owner in owners - current_owners:
                    hub.detach(listener, routing_key(owner))
                    if current and current_owner == owner:
                        hub.detach(listener, routing_key(owner, current))
                        current = None
                        current_owner = None
                if current_owners != owners:
                    ws.send(json.dumps({'event': 'jobs.snapshot', **client.call('progress.list')}, ensure_ascii=False))
                owners = current_owners
                ws.send(json.dumps({'event': 'service.status', 'status': client.call('service.status')}))
                checked = time.monotonic()
    except ClientError as exc:
        if exc.status == 401:
            try:
                ws.send(json.dumps({'event': 'session.expired'}))
            except Exception:
                pass
        else:
            raise
    finally:
        hub.detach(listener)
        ws.close()
