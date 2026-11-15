"""모델 호출 중 이벤트 루프와 비용 저장 경계."""
import asyncio
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from backend.providers.llm_provider import ChatModelProvider


def test_model_call_awaits_reservation_and_settlement(monkeypatch):
    async def scenario():
        meter = SimpleNamespace(reserve=AsyncMock(return_value="reservation"),
                                record_usage=AsyncMock(), settle=AsyncMock())
        class Client:
            def __init__(self, **_kwargs):
                pass
            def close(self):
                pass
        class Model:
            def invoke(self, _inputs):
                return AIMessage(content="ok")
        monkeypatch.setattr("backend.providers.llm_provider.httpx2.Client", Client)
        monkeypatch.setattr("backend.providers.llm_provider.init_chat_model", lambda *_a, **_k: Model())
        monkeypatch.setattr("backend.providers.llm_provider.require_model", lambda *_: None)
        before = AsyncMock()
        provider = ChatModelProvider(api_key="fake-value", meter=meter)
        result = await provider.complete_result([{"role": "user", "content": "hello"}],
                                                model="fake-model", conversation_id="conv_fake", before_request=before)
        assert result.text == "ok"
        meter.reserve.assert_awaited_once()
        meter.settle.assert_awaited_once()
        before.assert_awaited_once()
    asyncio.run(scenario())


def test_cancelled_inflight_request_keeps_uncertain_cost(monkeypatch):
    async def scenario():
        entered, release = Event(), Event()
        meter = SimpleNamespace(reserve=AsyncMock(return_value="reservation"),
                                record_usage=AsyncMock(), settle=AsyncMock())
        class Client:
            def __init__(self, **_kwargs):
                pass
            def close(self):
                pass
        class Model:
            def invoke(self, _inputs):
                entered.set()
                release.wait(2)
                return AIMessage(content="ok")
        monkeypatch.setattr("backend.providers.llm_provider.httpx2.Client", Client)
        monkeypatch.setattr("backend.providers.llm_provider.init_chat_model", lambda *_a, **_k: Model())
        monkeypatch.setattr("backend.providers.llm_provider.require_model", lambda *_: None)
        provider = ChatModelProvider(api_key="fake-value", meter=meter)
        task = asyncio.create_task(provider.complete_result([{"role": "user", "content": "hello"}],
                                   model="fake-model", conversation_id="conv_fake"))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        meter.settle.assert_awaited_once_with("reservation", "fake-model", None)
    asyncio.run(scenario())


def test_one_hundred_blocking_model_transports_can_start_concurrently(monkeypatch):
    async def scenario():
        count, lock, ready, release = 0, Lock(), Event(), Event()
        class Client:
            def __init__(self, **_kwargs):
                pass
            def close(self):
                pass
        class Model:
            def invoke(self, _inputs):
                nonlocal count
                with lock:
                    count += 1
                    if count == 100:
                        ready.set()
                release.wait(4)
                return AIMessage(content="ok")
        monkeypatch.setattr("backend.providers.llm_provider.httpx2.Client", Client)
        monkeypatch.setattr("backend.providers.llm_provider.init_chat_model", lambda *_a, **_k: Model())
        monkeypatch.setattr("backend.providers.llm_provider.require_model", lambda *_: None)
        provider = ChatModelProvider(api_key="fake-value")
        tasks = [asyncio.create_task(provider.complete_result([{"role": "user", "content": "x"}],
                 model="fake-model", conversation_id="conv_fake")) for _ in range(100)]
        try:
            assert await asyncio.to_thread(ready.wait, 2), f"only {count} transports started"
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(scenario())
