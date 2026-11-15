"""공개 RPC가 비동기 서비스 응답을 완료한 뒤 직렬화한다."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.server.app import Server


def test_dispatch_awaits_public_service_result():
    async def scenario():
        server = Server.__new__(Server)
        server.public = SimpleNamespace(invoke=AsyncMock(return_value={"id": "done"}))
        request = {"request_id": "req", "method": "auth.me", "params": {}}
        packet = json.loads(await server._dispatch(request))
        assert packet["result"] == {"id": "done"}
        server.public.invoke.assert_awaited_once()
    asyncio.run(scenario())


def test_linked_account_receives_progress_from_authorized_physical_owner():
    async def scenario():
        server = Server.__new__(Server)
        queue = asyncio.Queue()
        server.subscribers = {queue}
        server.public = True
        server.subscriber_owners = {queue: ("representative", "guest")}
        server.manager = SimpleNamespace(jobs={})
        server._publish({"event": "job.changed", "job": {"id": "j"}, "_owner_id": "guest"})
        assert json.loads(queue.get_nowait())["event"] == "job.changed"
    asyncio.run(scenario())


def test_windows_entrypoint_uses_selector_event_loop(monkeypatch):
    from backend.server import app
    seen = []
    class Runner:
        def __init__(self, *, loop_factory):
            seen.append(loop_factory)
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def run(self, coroutine):
            coroutine.close()
    monkeypatch.setattr(app, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(app.asyncio, "Runner", Runner)
    app.run()
    assert seen == [asyncio.SelectorEventLoop]


def test_subscription_closes_without_sending_queued_events_when_principal_changes():
    async def scenario():
        server = Server.__new__(Server)
        queue = asyncio.Queue()
        await queue.put('{"event":"private"}')
        server.subscriber_owners = {queue: ('account',)}
        server.public = SimpleNamespace(access=SimpleNamespace(
            resolve_session=AsyncMock(return_value=('guest', {'id': 'guest', 'owner_ids': ['guest']}))))
        socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
        await server._sender(socket, queue, 'expired', 'guest', {'id': 'account', 'owner_ids': ['account']})
        socket.send.assert_not_awaited()
        socket.close.assert_awaited_once_with(code=1008)
    asyncio.run(scenario())


def test_subscribe_accepts_valid_alternate_when_primary_is_expired():
    async def scenario():
        class Socket:
            remote_address = ('127.0.0.1', 1)
            request = None
            def __init__(self): self.messages = []
            def __aiter__(self): return self
            async def __anext__(self):
                if self.messages: raise StopAsyncIteration
                return json.dumps({'request_id': 'r', 'method': 'subscribe', 'params': {},
                                   'session': 'expired', 'guest_session': 'guest'})
            async def send(self, msg): self.messages.append(json.loads(msg))
            async def close(self, **kwargs): pass
        server = Server.__new__(Server)
        server.public = SimpleNamespace(access=SimpleNamespace(
            session=AsyncMock(side_effect=ValueError('expired')),
            resolve_session=AsyncMock(return_value=('guest', {'id': 'guest', 'owner_ids': ['guest']}))))
        server.internal_key = ''
        server.subscribers = set()
        server.subscriber_owners = {}
        socket = Socket()
        await server.handler(socket)
        assert socket.messages[0].get('result') == {'ready': True}
    asyncio.run(scenario())
