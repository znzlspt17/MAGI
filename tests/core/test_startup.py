"""백엔드는 잠금·마이그레이션·복구 순서를 지키고 준비 실패 시 잠금을 해제한다."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.server import app
from backend.access import runtime as access_runtime
from backend.knowledge import setup
from backend.knowledge.config import KnowledgeConfig
from protocol import deployment


@pytest.mark.parametrize("failure", [None, "migration", "service"])
def test_startup_prepares_database_before_accepting_requests(monkeypatch, failure):
    from backend.knowledge import runtime as knowledge_runtime

    events = []
    store = object()

    class Runtime:
        def __init__(self, value):
            assert value is store
            self.store, self.connection = value, None

        def acquire(self, *, recover):
            assert recover is False
            self.connection = object()
            events.append("lock")

        def recover(self):
            events.append("recover")

        def close(self):
            self.connection = None
            events.append("unlock")

    def migrate(value, *, runtime):
        assert value is store and runtime.connection is not None
        events.append("migration")
        if failure == "migration":
            raise setup.MigrationError("테스트 준비 실패")

    def knowledge(value):
        assert value is store
        events.append("service")
        if failure == "service":
            raise RuntimeError("test-service-failure")
        return object()

    @asynccontextmanager
    async def serve(*args, **kwargs):
        events.append("listen")
        yield

    class Event:
        async def wait(self):
            return

        def set(self):
            pass

    monkeypatch.setattr(app, "os", SimpleNamespace(environ={}))
    monkeypatch.setattr(app, "configure_logging", lambda: None)
    monkeypatch.setattr(app, "_log_exception", lambda *args: None)
    monkeypatch.setattr(deployment, "validate_container", lambda role: None)
    monkeypatch.setattr(KnowledgeConfig, "from_env", lambda: object())
    monkeypatch.setattr("backend.knowledge.store.KnowledgeStore", lambda config: store)
    monkeypatch.setattr(access_runtime, "PublicRuntime", Runtime)
    monkeypatch.setattr(setup, "migrate", migrate)
    monkeypatch.setattr(knowledge_runtime, "KnowledgeService", knowledge)
    monkeypatch.setattr(app, "Server", lambda *args, **kwargs: SimpleNamespace(
        handler=None, manager=SimpleNamespace(close=lambda: events.append("close")),
    ))
    monkeypatch.setattr(app, "serve", serve)
    monkeypatch.setattr(app.asyncio, "Event", Event)
    if failure:
        with pytest.raises(SystemExit) as caught:
            asyncio.run(app.main())
        assert caught.value.code == 1
        assert "listen" not in events
    else:
        asyncio.run(app.main())
        assert events == ["lock", "migration", "recover", "service", "listen", "close", "unlock"]
    assert events[-1] == "unlock"
    if failure == "migration":
        assert events == ["lock", "migration", "unlock"]
