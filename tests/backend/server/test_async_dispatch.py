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
