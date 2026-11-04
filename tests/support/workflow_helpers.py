"""여러 테스트에서 공유하는 검증용 도우미."""

from unittest.mock import Mock
from types import SimpleNamespace
from backend.engine import Engine
from backend.server.job_manager import JobManager
from tests.support.fakes import DecisionProvider


def manager_for(store, monkeypatch, provider=None):
    service = SimpleNamespace(
        store=store,
        close=lambda: None,
        schedule=lambda: None,
        context=lambda *a, **kw: {"nodes": [], "edges": [], "mode": "text"},
    )
    provider = provider or DecisionProvider([[], [], [], []])
    manager = JobManager(
        service,
        engine_factory=lambda docs, runtime: Engine(docs, runtime, provider=provider),
    )
    monkeypatch.setattr(manager, "_submit_locked", Mock())
    return manager, provider
